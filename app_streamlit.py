import os
import tempfile
import traceback
import streamlit as st
import pandas as pd

from help import xlsx_name_from_pdf
from extractor.pipeline import pdf_to_excel_batched

# ---- Model choices
MODEL_CHOICES = {
    "Gemini 2.5 Flash": "gemini-2.5-flash",  # default
    "Gemini 2.5 Flash Lite": "gemini-2.5-flash-lite",
    "Gemini 2.0 Flash": "gemini-2.0-flash",
    "Gemini 2.0 Flash Lite": "gemini-2.0-flash-lite",
    "Gemini 2.5 Pro": "gemini-2.5-pro",
    "Gemini 2.0 Flash Experimental": "gemini-2.0-flash-exp",
    "LearnLM 2.0 Flash Experimental": "learnlm-2.0-flash-experimental",
}

st.set_page_config(page_title="Bank PDF → Excel (Gemini, fast)", layout="centered")
st.title("Bank Statement Extractor — Gemini (fast + structured)")

# ---- API Key from Streamlit Secrets (preferred) or env fallback
try:
    GOOGLE_API_KEY = st.secrets["GOOGLE_API_KEY"]
except Exception:
    GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")

if not GOOGLE_API_KEY:
    st.error("Set GOOGLE_API_KEY in Streamlit Secrets (or as an env var) and rerun.")
    st.stop()

# ---- Model dropdown
model_label = st.selectbox("Gemini model", list(MODEL_CHOICES.keys()), index=0)
model_id = MODEL_CHOICES[model_label]

# ---- Upload
pdf_file = st.file_uploader("Upload a bank statement PDF", type=["pdf"])

# ---- Advanced
with st.expander("Advanced"):
    batch_size = st.number_input("Lines per batch (speed vs. cost)", min_value=1, max_value=50, value=8, step=1)
    max_output_tokens = st.number_input("Max output tokens / call", min_value=256, max_value=8192, value=2048, step=256)
    use_layout = st.checkbox("Use PyMuPDF Layout (if installed)", value=True,
                             help="Activates pymupdf.layout if present for better layout & tables.")
    skip_filter = st.checkbox("Skip obvious non-transaction lines", value=True)

# ---- Session error log
if "error_log" not in st.session_state:
    st.session_state["error_log"] = []
error_log = st.session_state["error_log"]

# ---- Extract
if st.button("Extract to Excel", type="primary") and pdf_file:
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        tmp.write(pdf_file.read())
        tmp_pdf = tmp.name

    out_name = xlsx_name_from_pdf(pdf_file.name)
    out_path = os.path.join(os.path.dirname(tmp_pdf), out_name)

    try:
        with st.spinner(f"Parsing + extracting with {model_id}…"):
            df = pdf_to_excel_batched(
                pdf_path=tmp_pdf,
                out_xlsx_path=out_path,
                google_api_key=GOOGLE_API_KEY,
                model_id=model_id,
                batch_size=int(batch_size),
                max_output_tokens=int(max_output_tokens),
                use_layout=use_layout,
                skip_non_txn_filter=skip_filter,
                error_log=error_log,
            )
        st.success(f"Done. Extracted {len(df)} rows.")
        if not df.empty:
            st.dataframe(df.head(50), use_container_width=True)

        with open(out_path, "rb") as f:
            st.download_button(
                "Download Excel",
                data=f.read(),
                file_name=out_name,
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
    except Exception as e:
        tb = traceback.format_exc()
        st.error(f"Extraction failed: {e}")
        error_log.append(tb)
    finally:
        try:
            os.remove(tmp_pdf)
            if os.path.exists(out_path):
                os.remove(out_path)
        except Exception:
            pass

# ---- Error log
st.subheader("Error log")
if error_log:
    st.code("\n\n".join(error_log[-5:]), language="text")
else:
    st.caption("No errors yet.")