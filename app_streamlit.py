import os
import tempfile
import streamlit as st
import pandas as pd

from extractor import parse_pdf_to_excel  # works because __init__.py re-exports it

MODEL_CHOICES = [
    "microsoft/Phi-3-mini-4k-instruct",   # fast on CPU
    "Qwen/Qwen2.5-3B-Instruct",          # stronger, heavier
    "mistralai/Mistral-7B-Instruct-v0.2" # heavier on CPU; use only if you can
]

st.set_page_config(page_title="Bank PDF → Excel (Local HF CPU)", layout="centered")
st.title("Bank Statement Extractor — Local HF (CPU) | Page-by-page")

model_name = st.selectbox("Local model", MODEL_CHOICES, index=0)
pdf_file = st.file_uploader("Upload a bank statement PDF", type=["pdf"])

with st.expander("Advanced"):
    max_new_tokens = st.number_input("Max new tokens per page", 200, 2000, 900, 50)
    temperature = st.number_input("Temperature", 0.0, 1.0, 0.0, 0.1)

if st.button("Extract to Excel") and pdf_file:
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        tmp.write(pdf_file.read())
        tmp_pdf = tmp.name

    out_xlsx = tmp_pdf.replace(".pdf", ".xlsx")

    with st.spinner(f"Parsing with {model_name} (CPU)…"):
        try:
            df = parse_pdf_to_excel(
                pdf_path=tmp_pdf,
                model_name=model_name,
                out_path=out_xlsx,
                max_new_tokens=int(max_new_tokens),
                temperature=float(temperature),
            )
            st.success(f"Done. Extracted {len(df)} rows.")
            if not df.empty:
                st.dataframe(df.head(50), use_container_width=True)
            with open(out_xlsx, "rb") as f:
                st.download_button(
                    "Download Excel",
                    data=f.read(),
                    file_name=os.path.basename(out_xlsx),
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
        except Exception as e:
            st.error(f"Extraction failed: {e}")
        finally:
            # cleanup temp files
            try:
                os.remove(tmp_pdf)
                if os.path.exists(out_xlsx):
                    os.remove(out_xlsx)
            except Exception:
                pass