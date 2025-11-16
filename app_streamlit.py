import os
import io
import tempfile
import streamlit as st
import pandas as pd

from help import xlsx_name_from_pdf
from extractor.pipeline import pdf_to_excel_linewise

st.set_page_config(page_title=" Statement Extractor (Local CPU)", layout="centered")
st.title(" Statement Extractor — Local CPU (PyMuPDF4LLM + LMFE)")

# 1) Model dropdown
model_choices = [
    "Qwen/Qwen2.5-3B-Instruct",        # accuracy for structured JSON
    "microsoft/Phi-3-mini-4k-instruct" # lighter + faster
]
model_id = st.selectbox("LLM model", model_choices, index=0,
                        help="CPU-friendly instruct models. Qwen2.5-3B excels at structured JSON; Phi-3-mini is faster.")

# 2) File upload
pdf_file = st.file_uploader("Upload  statement PDF", type=["pdf"])

# Advanced toggles
with st.expander("Advanced"):
    use_layout = st.checkbox("Use PyMuPDF Layout (if installed)", value=True,
                             help="If pymupdf.layout is available, it enhances layout & table detection.")
    max_new_tokens = st.number_input("Max new tokens / line", min_value=100, max_value=800, value=350, step=50)
    skip_filter = st.checkbox("Skip non-transaction-like lines (recommended)", value=True)

# 3) Extract button + 4) preview + 5) download + 6) error logs
error_log = st.session_state.setdefault("error_log", [])

if st.button("Extract", type="primary") and pdf_file:
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        tmp.write(pdf_file.read())
        tmp_pdf = tmp.name

    out_name = xlsx_name_from_pdf(pdf_file.name)
    out_path = os.path.join(os.path.dirname(tmp_pdf), out_name)

    st.info("Parsing with PyMuPDF4LLM (layout-friendly) and extracting line-by-line…")
    try:
        df = pdf_to_excel_linewise(
            pdf_path=tmp_pdf,
            out_xlsx_path=out_path,
            model_id=model_id,
            max_new_tokens=int(max_new_tokens),
            use_layout=use_layout,
            skip_non_txn_filter=skip_filter,
            error_log=error_log,
        )

        st.success(f"Done. Extracted {len(df)} rows.")
        if not df.empty:
            st.dataframe(df.head(50), use_container_width=True)

        # Offer download
        with open(out_path, "rb") as f:
            excel_bytes = f.read()
        st.download_button(
            "Download Excel",
            data=excel_bytes,
            file_name=out_name,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    except Exception as e:
        st.error(f"Extraction failed: {e}")
        error_log.append(str(e))
    finally:
        try:
            os.remove(tmp_pdf)
            if os.path.exists(out_path):
                os.remove(out_path)
        except Exception:
            pass

# Error log area
st.subheader("Error log")
if error_log:
    st.code("\n".join(error_log), language="text")
else:
    st.caption("No errors yet.")