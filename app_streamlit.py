import os
import tempfile
import traceback
import streamlit as st
import pandas as pd

from help import xlsx_name_from_pdf
from extractor.pipeline import pdf_to_excel_linewise

st.set_page_config(page_title=" Statement Extractor (OpenRouter)", layout="centered")
st.title(" Statement Extractor — OpenRouter (free tier)")

# --- Read the OpenRouter API key from Streamlit secrets securely ---
# Preferred: st.secrets["OPENROUTER_API_KEY"]
# Optional fallback: env var (remove the fallback if you want secrets-only)
api_key = None
try:
    api_key = st.secrets["OPENROUTER_API_KEY"]
except Exception:
    api_key = os.getenv("OPENROUTER_API_KEY", None)

if not api_key:
    st.error(
        "OPENROUTER_API_KEY is not set. Add it to Streamlit **Secrets** "
        "(or set the environment variable) and rerun the app."
    )
    st.stop()

# --- Curated list of OpenRouter free models suited to structured text extraction ---
MODEL_CHOICES = [
    "meta-llama/llama-3.3-70b-instruct:free",
    "mistralai/mistral-small-3.2-24b-instruct:free",
    "deepseek/deepseek-chat-v3.1:free",
    "qwen/qwen-2.5-72b-instruct:free",
    "google/gemma-3-12b-it:free",
]
model_id = st.selectbox("OpenRouter model", MODEL_CHOICES, index=0)

# --- File upload ---
pdf_file = st.file_uploader("Upload  statement PDF", type=["pdf"])

# --- Advanced options ---
with st.expander("Advanced"):
    use_layout = st.checkbox("Use PyMuPDF Layout (if installed)", value=True,
                             help="If 'pymupdf.layout' is available, it improves layout & table detection.")
    max_tokens = st.number_input("Max tokens per response", min_value=512, max_value=8192, value=8192, step=256)
    temperature = st.number_input("Temperature", min_value=0.0, max_value=1.0, value=0.0, step=0.1)
    skip_filter = st.checkbox("Skip non-transaction-like lines", value=True)

# --- Session-scoped error log ---
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
        with st.spinner(f"Parsing with PyMuPDF4LLM and extracting via {model_id} (OpenRouter)…"):
            df = pdf_to_excel_linewise(
                pdf_path=tmp_pdf,
                out_xlsx_path=out_path,
                model_id=model_id,
                api_key=api_key,                # <<– from secrets
                max_tokens=int(max_tokens),
                temperature=float(temperature),
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

# --- Error log panel ---
st.subheader("Error log")
if error_log:
    st.code("\n\n".join(error_log[-5:]), language="text")
else:
    st.caption("No errors yet.")