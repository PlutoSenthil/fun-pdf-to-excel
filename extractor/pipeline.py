import os
import pandas as pd
from typing import Optional, List, Dict, Any

from pydantic import ValidationError
from .schema import TransactionRow
from .layout_extract import extract_lines_pymupdf4llm
from .llm_constrained import LMFEConstrained, SYSTEM_PROMPT, build_user_prompt

def pdf_to_excel_linewise(
    pdf_path: str,
    out_xlsx_path: str,
    model_id: str = "Qwen/Qwen2.5-3B-Instruct",
    max_new_tokens: int = 350,
    use_layout: bool = True,
    skip_non_txn_filter: bool = True,
    error_log: Optional[List[str]] = None,
) -> pd.DataFrame:
    """
    Extracts lines with PyMuPDF4LLM (layout-enhanced if available),
    generates exactly-one JSON TransactionRow per line with LMFE-constrained decoding,
    and writes a DataFrame with page/line_index to out_xlsx_path.
    Returns the DataFrame.
    """
    if error_log is None:
        error_log = []

    pages_lines, header_hints = extract_lines_pymupdf4llm(
        pdf_path=pdf_path,
        use_layout=use_layout,
        table_strategy="lines_strict",
        page_chunks=True,
    )

    llm = LMFEConstrained(model_id=model_id, max_new_tokens=max_new_tokens)

    records: List[Dict[str, Any]] = []

    for page_idx, (lines, header_hint) in enumerate(zip(pages_lines, header_hints), start=1):
        page_count = 0
        for line_idx, line in enumerate(lines, start=1):
            if skip_non_txn_filter:
                has_amountish = any(ch.isdigit() for ch in line) and ('.' in line or ',' in line)
                has_dateish = ('-' in line or '/' in line)
                if not (has_amountish or has_dateish):
                    continue

            user_prompt = build_user_prompt(page_idx, line_idx, line, header_hint)

            try:
                obj = llm.generate_one_row(SYSTEM_PROMPT, user_prompt, max_new_tokens=max_new_tokens)
                row = TransactionRow(**obj)
                rec = row.model_dump()
                rec["page"] = page_idx
                rec["line_index"] = line_idx
                records.append(rec)
                page_count += 1
            except ValidationError as ve:
                error_log.append(f"[Page {page_idx} Line {line_idx}] pydantic error: {ve}")
            except Exception as e:
                error_log.append(f"[Page {page_idx} Line {line_idx}] LLM error: {e}")

        # simple page progress
        # (intentionally quiet in lib; the app shows aggregate counts)
        # print(f"Page {page_idx}: {page_count} rows")

    df = pd.DataFrame(records)

    # Optional: order by dates then page-line (keeps your expected ordering)
    def dmy_key(s: str):
        try:
            d, m, y = s.split("-")
            return (int(y), int(m), int(d))
        except Exception:
            return (9999, 12, 31)

    if not df.empty:
        df["__sv"] = df["value_date"].map(dmy_key)
        df["__sp"] = df["post_date"].map(dmy_key)
        df = df.sort_values(["__sv", "__sp", "page", "line_index"]).drop(columns=["__sv", "__sp"], errors="ignore")

    # Write Excel
    df.to_excel(out_xlsx_path, index=False)
    return df