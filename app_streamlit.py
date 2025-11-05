# app.py
import streamlit as st
import pandas as pd
import numpy as np
import io, os, re
from pathlib import Path
from datetime import datetime
from dateutil import parser as dparser

import fitz  # PyMuPDF
import pdfplumber

# Digital table tools
import camelot

# OCR stack (soft optional)
import pytesseract
from pdf2image import convert_from_path
from PIL import Image

# Optional (better tables for scanned)
try:
    from paddleocr import PPStructure
    HAVE_PADDLE = True
except Exception:
    HAVE_PADDLE = False

# ---------- Simple config ----------
UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)

st.set_page_config(page_title="Bank Statement Extractor (Simple MVP)", layout="wide")
st.title("🏦 Simple Multi‑Bank Statement Extractor (India) – MVP")

# ---------- Helpers ----------

def is_scanned_pdf(path: str, text_thresh: int = 200) -> bool:
    """Heuristic: if pretty much no extractable text across pages → scanned."""
    try:
        doc = fitz.open(path)
        cnt = 0
        for page in doc:
            cnt += len(page.get_text("text"))
            if cnt >= text_thresh:
                return False
        return True
    except Exception:
        return False

AMOUNT_JUNK = re.compile(r'[^\d\-\.,()]')

def parse_amount(s):
    if s is None:
        return None
    s = str(s)
    if s.strip() in ["", "-", "—", "None", "nan"]:
        return None
    # Remove currency/suffix noise
    s = s.replace("₹", "").replace("INR", "").replace("Cr", "").replace("CR", "").replace("Dr", "").replace("DR", "")
    s = AMOUNT_JUNK.sub("", s).replace(",", "")
    if s.strip() == "":
        return None
    neg = "(" in s and ")" in s
    s = s.replace("(", "").replace(")", "")
    try:
        val = float(s)
        return -val if neg else val
    except Exception:
        return None

MONTHS = {
    'jan':1,'feb':2,'mar':3,'apr':4,'may':5,'jun':6,'jul':7,'aug':8,'sep':9,'oct':10,'nov':11,'dec':12
}

def normalize_date(s):
    s = (s or "").strip()
    if not s:
        return s
    # Fast paths for Indian formats
    for fmt in ["%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%d/%m/%y", "%d-%b-%Y", "%d-%b-%y", "%d %b %Y", "%d %B %Y"]:
        try:
            dt = datetime.strptime(s, fmt)
            return dt.strftime("%d/%m/%Y")
        except Exception:
            pass
    # Generic fuzzy parse (last resort)
    try:
        dt = dparser.parse(s, dayfirst=True, fuzzy=True)
        return dt.strftime("%d/%m/%Y")
    except Exception:
        return s  # leave as-is

# Column candidates (wide coverage for Indian banks)
DATE_COLS   = ['date', 'txn date', 'transaction date', 'value date', 'posting date']
DESC_COLS   = ['description', 'narration', 'particulars', 'remarks', 'details', 'transaction details']
REF_COLS    = ['chq no', 'cheque no', 'cheque no.', 'ref no', 'reference no', 'reference', 'utr', 'upi', 'transaction id', 'instrument no', 'ref']
DEBIT_COLS  = ['debit', 'withdrawal', 'withdrawals', 'dr', 'amount dr', 'withdrawal (dr)']
CREDIT_COLS = ['credit', 'deposit', 'deposits', 'cr', 'amount cr', 'deposit (cr)']
BAL_COLS    = ['balance', 'running balance', 'closing balance', 'balance amount', 'avail balance', 'available balance']

def pick_col(cols, candidates):
    cols_l = [c.lower().strip() for c in cols]
    for idx, c in enumerate(cols_l):
        for can in candidates:
            if c == can or c.startswith(can):
                return list(cols)[idx]
    return None

def clean_df(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    df = df.copy()
    df.columns = [str(c).strip().lower() for c in df.columns]
    df = df.loc[:, ~df.columns.duplicated(keep="first")]
    df = df.dropna(how="all").reset_index(drop=True)
    for c in df.columns:
        df[c] = df[c].astype(str).str.replace("\n", " ").str.strip()
    return df

def merge_wrapped_rows(df, date_col, debit_col, credit_col, bal_col):
    """Rows without date/amount/balance extend the previous narration."""
    out = []
    buffer = None
    for _, r in df.iterrows():
        def has(x):
            s = str(x).strip().lower()
            return s not in ["", "-", "nan", "none", "—"]
        is_cont = not has(r.get(date_col)) and not has(r.get(debit_col)) and not has(r.get(credit_col)) and not has(r.get(bal_col))
        if is_cont and buffer is not None:
            # Append continuation into description-like fields
            joiner = ' ' + ' '.join([str(v) for v in r.values if str(v).strip() not in ["", "-", "nan", "none"]])
            buffer[1][buffer[0]['desc_col']] = (str(buffer[1].get(buffer[0]['desc_col'], "")) + " " + joiner).strip()
        else:
            meta = {'desc_col': pick_col(df.columns, DESC_COLS) or (df.columns[1] if len(df.columns) > 1 else df.columns[0])}
            buffer = (meta, r)
            out.append(buffer)
    # return DataFrame
    rows = [r for _, r in out]
    return pd.DataFrame(rows).reset_index(drop=True)

def extract_tables_digital(path: str):
    tables = []
    # 1) Lattice preserves cell grid (best for ruled bank tables)
    try:
        t = camelot.read_pdf(path, pages="all", flavor="lattice", strip_text="\n")
        tables += [tbl.df for tbl in t]
    except Exception:
        pass
    # 2) Stream for non-ruled layouts
    if not tables:
        try:
            t = camelot.read_pdf(path, pages="all", flavor="stream", row_tol=12, column_tol=8, strip_text="\n")
            tables += [tbl.df for tbl in t]
        except Exception:
            pass
    # 3) Fallback to pdfplumber
    if not tables:
        try:
            with pdfplumber.open(path) as pdf:
                for page in pdf.pages:
                    tbs = page.extract_tables()
                    for tb in tbs:
                        df = pd.DataFrame(tb[1:], columns=tb[0])
                        tables.append(df)
        except Exception:
            pass
    return [clean_df(df) for df in tables if df is not None]

def extract_tables_scanned(path: str):
    """Prefer PaddleOCR PP-Structure when available; else Tesseract text-only fallback."""
    dfs = []
    pages = convert_from_path(path, dpi=300)
    if HAVE_PADDLE:
        engine = PPStructure(show_log=False, ocr=True, layout=True, table=True)
        for img in pages:
            with Image.fromarray(np.array(img)) as im:
                # Save to temp file path-like
                tmp = UPLOAD_DIR / "_tmp_scan.png"
                im.save(tmp)
                result = engine(str(tmp))
                for block in result:
                    if block.get("type") == "table" and "res" in block and "html" in block["res"]:
                        try:
                            df = pd.read_html(block["res"]["html"])[0]
                            dfs.append(df)
                        except Exception:
                            pass
        return [clean_df(df) for df in dfs if df is not None]
    else:
        # Tesseract fallback: we can only get text reliably; use pdfplumber to try cell detection (weak).
        # For MVP, we’ll attempt pdfplumber tables after converting to PDF again (no-op).
        # Better: ask to install paddleocr for robust scans.
        st.warning("PaddleOCR not installed. Scanned table extraction will be less accurate. Install `paddleocr` for better results.")
        try:
            with pdfplumber.open(path) as pdf:
                for page in pdf.pages:
                    for tb in page.extract_tables():
                        df = pd.DataFrame(tb[1:], columns=tb[0])
                        dfs.append(df)
        except Exception:
            pass
        return [clean_df(df) for df in dfs if df is not None]

def select_transaction_tables(dfs):
    """Heuristic: choose tables with date + (debit/credit) + balance or largest table."""
    candidates = []
    for df in dfs:
        cols = [c.lower() for c in df.columns]
        has_date = any(any(c.startswith(x) for x in DATE_COLS) for c in cols)
        has_amt = any(any(c.startswith(x) for x in DEBIT_COLS + CREDIT_COLS) for c in cols)
        has_bal = any(any(c.startswith(x) for x in BAL_COLS) for c in cols)
        if has_date and (has_amt or has_bal):
            candidates.append(df)
    if candidates:
        return candidates
    # fallback: pick biggest
    if dfs:
        return [max(dfs, key=lambda d: len(d))]
    return []

def extract_full_text(path: str) -> str:
    txt = []
    try:
        doc = fitz.open(path)
        for p in doc:
            txt.append(p.get_text("text"))
    except Exception:
        pass
    return "\n".join(txt)

def parse_header(text: str):
    # Loose regex to work across banks
    bank = re.search(r'(?im)^\s*(HDFC|ICICI|STATE BANK OF INDIA|SBI|AXIS|KOTAK|IDFC FIRST|CANARA|YES|INDUSIND).*BANK', text)
    branch = re.search(r'(?i)\b(branch|br\.?)\s*[:\-]?\s*([A-Za-z0-9 /_\-]+)', text)
    holder = re.search(r'(?i)(customer name|account holder|acc(?:ount)? name|name)\s*[:\-]?\s*([A-Za-z][A-Za-z .]+)', text)
    period = re.search(r'(?i)(statement\s*period|period)\s*[:\-]?\s*([0-9A-Za-z /:\-]+to[0-9A-Za-z /:\-]+)', text)
    opening = re.search(r'(?i)(opening|initial|init\.?\s*bal(?:ance)?)\s*[:\-]?\s*₹?\s*([0-9,.\(\) -]+)', text)
    return {
        "bank_name": bank.group(0).strip() if bank else "Unknown Bank",
        "branch_name": branch.group(2).strip() if branch else "",
        "account_holder_name": holder.group(2).strip() if holder else "",
        "statement_period": period.group(2).strip() if period else "",
        "initial_balance": parse_amount(opening.group(2)) if opening else None
    }

def parse_footer(text: str):
    tot_debit = re.search(r'(?i)(total\s*debit|debit\s*total)\s*[:\-]?\s*₹?\s*([0-9,.\(\) -]+)', text)
    tot_credit = re.search(r'(?i)(total\s*credit|credit\s*total)\s*[:\-]?\s*₹?\s*([0-9,.\(\) -]+)', text)
    closing = re.search(r'(?i)(closing\s*bal(?:ance)?|available\s*bal(?:ance)?)\s*[:\-]?\s*₹?\s*([0-9,.\(\) -]+)', text)
    return {
        "total_debit_amount": parse_amount(tot_debit.group(2)) if tot_debit else None,
        "total_credit_amount": parse_amount(tot_credit.group(2)) if tot_credit else None,
        "closing_balance": parse_amount(closing.group(2)) if closing else None
    }

def extract_ref_from_desc(desc: str):
    m = re.search(r'(?i)(UPI|IMPS|NEFT|RTGS).*?(REF|UTR|TXN|ID)[:\s#-]*([A-Z0-9\-]{6,})', desc or "")
    return m.group(3) if m else None

def normalize_table_to_6cols(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame(columns=['date','reference_or_cheque_no','description','withdrawal_amount','credit_amount','balance'])
    cols = df.columns
    date_col  = pick_col(cols, DATE_COLS) or cols[0]
    desc_col  = pick_col(cols, DESC_COLS) or (cols[1] if len(cols) > 1 else cols[0])
    ref_col   = pick_col(cols, REF_COLS)
    debit_col = pick_col(cols, DEBIT_COLS)
    credit_col= pick_col(cols, CREDIT_COLS)
    bal_col   = pick_col(cols, BAL_COLS)

    # Merge wrapped rows (multi-line narration)
    df2 = merge_wrapped_rows(df, date_col, debit_col, credit_col, bal_col)

    out = []
    for _, r in df2.iterrows():
        ddate = normalize_date(r.get(date_col, ""))
        desc  = str(r.get(desc_col, "")).strip()
        ref   = str(r.get(ref_col, "")).strip() if ref_col else None
        debit = parse_amount(r.get(debit_col))
        credit= parse_amount(r.get(credit_col))
        bal   = parse_amount(r.get(bal_col))
        if not ref:
            ref = extract_ref_from_desc(desc)
        # Skip completely empty rows
        if (ddate == "" and desc == "" and debit is None and credit is None and bal is None):
            continue
        out.append({
            "date": ddate,
            "reference_or_cheque_no": ref if ref else None,
            "description": desc,
            "withdrawal_amount": debit if debit else None,
            "credit_amount": credit if credit else None,
            "balance": bal if bal is not None else np.nan
        })
    out_df = pd.DataFrame(out, columns=['date','reference_or_cheque_no','description','withdrawal_amount','credit_amount','balance'])
    return out_df

def build_statement_object(path: str):
    text = extract_full_text(path)
    header = parse_header(text)
    footer = parse_footer(text)

    dfs = extract_tables_scanned(path) if is_scanned_pdf(path) else extract_tables_digital(path)
    tx_dfs = select_transaction_tables(dfs)

    if not tx_dfs:
        tx_norm = pd.DataFrame(columns=['date','reference_or_cheque_no','description','withdrawal_amount','credit_amount','balance'])
    else:
        tx_norm = pd.concat([normalize_table_to_6cols(d) for d in tx_dfs], ignore_index=True)
        tx_norm = tx_norm.dropna(how="all", subset=['date','description','withdrawal_amount','credit_amount','balance'])

    # Derive missing balances
    initial = header.get("initial_balance")
    if initial is None and len(tx_norm) > 0 and pd.notna(tx_norm.iloc[0]['balance']):
        first = tx_norm.iloc[0]
        if pd.notna(first['credit_amount']):
            initial = float(first['balance']) - float(first['credit_amount'])
        elif pd.notna(first['withdrawal_amount']):
            initial = float(first['balance']) + float(first['withdrawal_amount'])

    total_debit  = float(tx_norm['withdrawal_amount'].fillna(0).sum()) if len(tx_norm) else 0.0
    total_credit = float(tx_norm['credit_amount'].fillna(0).sum()) if len(tx_norm) else 0.0
    closing = footer.get("closing_balance")
    if closing is None and len(tx_norm) and pd.notna(tx_norm.iloc[-1]['balance']):
        closing = float(tx_norm.iloc[-1]['balance'])
    if closing is None and initial is not None:
        closing = float(initial) + total_credit - total_debit

    return {
        "header": {
            "bank_name": header["bank_name"],
            "branch_name": header["branch_name"],
            "account_holder_name": header["account_holder_name"],
            "statement_period": header["statement_period"],
            "initial_balance": float(initial) if initial is not None else 0.0
        },
        "transactions": tx_norm,
        "footer": {
            "total_debit_amount": float(footer.get("total_debit_amount") or total_debit),
            "total_credit_amount": float(footer.get("total_credit_amount") or total_credit),
            "closing_balance": float(closing or 0.0)
        }
    }

def export_to_excel(df: pd.DataFrame) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        df.to_excel(xw, index=False, sheet_name="Transactions")
    return buf.getvalue()

# ---------- Streamlit UI ----------

tab1, tab2 = st.tabs(["Upload & Extract", "Export Specific File ➜ Excel"])

with tab1:
    st.subheader("Upload PDFs (digital or scanned)")
    files = st.file_uploader("Choose PDF files", type=["pdf"], accept_multiple_files=True)
    if st.button("Process"):
        if not files:
            st.info("Please upload at least one PDF.")
        else:
            for f in files:
                path = UPLOAD_DIR / f.name
                with open(path, "wb") as out:
                    out.write(f.read())
                with st.spinner(f"Extracting tables from {f.name} ..."):
                    stmt = build_statement_object(str(path))
                tx = stmt["transactions"]
                st.success(f"Done: {f.name} → {len(tx)} rows")
                st.json(stmt["header"])
                st.dataframe(tx, use_container_width=True, height=320)
                # Save normalized CSV for later export / re-use
                tx.to_csv(UPLOAD_DIR / f"{f.name}.csv", index=False)

with tab2:
    st.subheader("Pick a previously processed file and export to Excel")
    processed = [p.name for p in UPLOAD_DIR.glob("*.pdf") if (UPLOAD_DIR / f"{p.name}.csv").exists()]
    chosen = st.selectbox("Select file", processed)
    if chosen:
        df = pd.read_csv(UPLOAD_DIR / f"{chosen}.csv")
        st.dataframe(df, use_container_width=True, height=320)
        xls = export_to_excel(df)
        st.download_button(
            "⬇️ Download Excel",
            data=xls,
            file_name=f"{chosen}_transactions.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

st.caption("Tip: Install `paddleocr` for best scanned‑PDF table accuracy. Lattice-first Camelot preserves digital tables.")