import streamlit as st
import tempfile
import os
from extractor import parse_pdf_to_excel

MODEL_CHOICES = [
    "microsoft/Phi-3-mini-4k-instruct",
    "Qwen/Qwen2.5-3B-Instruct",
    "mistralai/Mistral-7B-Instruct-v0.2"
]

st.set_page_config(page_title="Bank PDF → Excel (Local LLM)", layout="centered")
st.title("Bank Statement Extractor — Local Hugging Face Model")

model_name = st.selectbox("Choose local model", MODEL_CHOICES, index=0)
pdf_file = st.file_uploader("Upload bank statement PDF", type=["pdf"])

if st.button("Extract") and pdf_file:
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        tmp.write(pdf_file.read())
        tmp_pdf = tmp.name

    out_path = tmp_pdf.replace(".pdf", ".xlsx")

    with st.spinner("Processing..."):
        df = parse_pdf_to_excel(tmp_pdf, model_name, out_path)

    st.success(f"Done! Extracted {len(df)} rows.")
    st.dataframe(df.head(50))

    with open(out_path, "rb") as f:
        st.download_button("Download Excel", f.read(), file_name=os.path.basename(out_path),
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    os.remove(tmp_pdf)
    os.remove(out_path)