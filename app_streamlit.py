import os
import tempfile
import traceback
import streamlit as st
import pandas as pd

from help import xlsx_name_from_pdf
from extractor.pipeline import pdf_to_excel_linewise

st.set_page_config(page_title="Bank Statement Extractor (OpenRouter + LangChain)", layout="centered")
st.title("Bank Statement Extractor — OpenRouter (LangChain)")

# --- Read the OpenRouter API key from Streamlit secrets (preferred) ---
try:
    API_KEY = st.secrets["OPENROUTER_API_KEY"]
except Exception:
    API_KEY = os.getenv("OPENROUTER_API_KEY")

if not API_KEY:
    st.error("OPENROUTER_API_KEY is not set. Add it to Streamlit Secrets or env and rerun.")
    st.stop()

# --- Curated free models for structured extraction (text-only) ---
MODEL_CHOICES = [
    "meta-llama/llama-3.3-70b-instruct:free",
    "mistralai/mistral-small-3.2-24b-instruct:free",
    "deepseek/deepseek-chat-v3.1:free",
    "qwen/qwen-2.5-72b-instruct:free",
    "google/gemma-3-12b-it:free",
]
model_id = st.selectbox("OpenRouter model", MODEL_CHOICES, index=0)

# --- File upload ---
pdf_file = st.file_uploader("Upload bank statement PDF", type=["pdf"])

# --- Advanced options ---
with st.expander("Advanced"):
    use_layout = st.checkbox("Use PyMuPDF Layout (if installed)", value=True,
                             help="If 'pymupdf.layout' is present, it improves layout & table detection.")
    max_tokens = st.number_input("Max tokens per response", min_value=512, max_value=8192, value=4096, step=256)
    temperature = st.number_input("Temperature", min_value=0.0, max_value=1.0, value=0.0, step=0.1)
    skip_filter = st.checkbox("Skip non-transaction-like lines", value=True)
    prefer_json_mode = st.checkbox("Prefer provider JSON mode (response_format=json) when supported", value=True)

# --- Error log (session) ---
if "error_log" not in st.session_state:
    st.session_state["error_log"] = []
error_log = st.session_state["error_log"]

# --- Extract button ---
if st.button("Extract", type="primary") and pdf_file:
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        tmp.write(pdf_file.read())
        tmp_pdf = tmp.name

    out_name = xlsx_name_from_pdf(pdf_file.name)
    out_path = os.path.join(os.path.dirname(tmp_pdf), out_name)

    try:
        with st.spinner(f"Parsing with PyMuPDF4LLM and extracting via {model_id}…"):
            df = pdf_to_excel_linewise(
                pdf_path=tmp_pdf,
                out_xlsx_path=out_path,
                model_id=model_id,
                api_key=API_KEY,
                max_tokens=int(max_tokens),
                temperature=float(temperature),
                use_layout=use_layout,
                skip_non_txn_filter=skip_filter,
                prefer_json_mode=prefer_json_mode,
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

# --- Error log panel ---
st.subheader("Error log")
if error_log:
    st.code("\n\n".join(error_log[-5:]), language="text")
else:
    st.caption("No errors yet.")