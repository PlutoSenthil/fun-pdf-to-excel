import streamlit as st
import pandas as pd
from pathlib import Path
from collections import defaultdict
import io
import zipfile
import pdfplumber
from modules.process_pdf import process_pdf
from modules.extract_logic import extract_data, build_dataframe

# --- App Setup ---
OUTPUT_DIR = Path("OUTPUT")
OUTPUT_DIR.mkdir(exist_ok=True)

st.set_page_config(page_title="ITR Comparison Tool", layout="wide")
st.title("📄 ITR Comparison Tool")

# --- Refresh / Start Fresh button (no explicit rerun needed) ---
top_cols = st.columns([2, 3, 3, 4])  # Refresh, upload badge, output badge, spacer
with top_cols[0]:
    if st.button("🔄 Refresh / Start Fresh", help="Clear OUTPUT and reset app state"):
        # Delete all files in OUTPUT
        for file in OUTPUT_DIR.glob("*"):
            try:
                file.unlink()
            except Exception:
                pass
        # Reset session state
        st.session_state.clear()
        # Recreate OUTPUT dir
        OUTPUT_DIR.mkdir(exist_ok=True)
        st.success("App refreshed. All previous data cleared.")

# --- Helper: count files in OUTPUT ---
def count_output_files():
    pdf_count = len(list(OUTPUT_DIR.glob("*.pdf")))
    txt_count = len(list(OUTPUT_DIR.glob("*_extracted.txt")))
    xlsx_count = len(list(OUTPUT_DIR.glob("*.xlsx")))
    total_count = len(list(OUTPUT_DIR.glob("*")))
    return pdf_count, txt_count, xlsx_count, total_count

# --- Session State Initialization ---
if "results" not in st.session_state:
    st.session_state.results = []

# --- Uploader (live badge for uploads) ---
uploaded_files = st.file_uploader("Upload ITR PDFs", type=["pdf"], accept_multiple_files=True)

# Live status badges (uploads + OUTPUT)
uploaded_count = len(uploaded_files) if uploaded_files else 0
pdf_count, txt_count, xlsx_count, total_count = count_output_files()

with top_cols[1]:
    st.metric(label="📥 Uploaded (this run)", value=uploaded_count)

with top_cols[2]:
    st.metric(label="📁 OUTPUT files", value=total_count, delta=f"PDF: {pdf_count} | TXT: {txt_count} | XLSX: {xlsx_count}")

# --- Form selection ---
form_type = st.selectbox("Select ITR Form", ["ITR1","ITR2"])
config_path = f"config/{form_type}_config.json"

# --- Result container class ---
class ITRResult:
    def __init__(self, file_name, extracted_rows, result, assessment_year, form_type, pan, df):
        self.file_name = file_name
        self.extracted_rows = extracted_rows
        self.result = result
        self.assessment_year = assessment_year
        self.form_type = form_type
        self.pan = pan
        self.df = df

# --- Extract Button & Processing ---
if uploaded_files:
    st.write(f"Uploaded {len(uploaded_files)} files.")

    if st.button("Extract Data"):
        if not Path(config_path).exists():
            st.error(f"Configuration file not found: {config_path}")
        else:
            progress = st.progress(0)
            total_files = len(uploaded_files)
            temp_results = []

            for idx, file in enumerate(uploaded_files):
                try:
                    input_path = OUTPUT_DIR / file.name
                    output_path = str(input_path).replace(".pdf", "_extracted.txt")

                    # Save uploaded file to disk
                    with open(input_path, "wb") as f:
                        f.write(file.getbuffer())

                    # Extract tables/text from PDF (pdfplumber)
                    extracted_rows = process_pdf(str(input_path), output_path)

                    # Apply regex config logic
                    result = extract_data(extracted_rows, config_path)

                    # Key fields for grouping/index
                    assessment_year = result['Assessment_Year']['Assessment_Year']
                    form_type_val = result['Form_Type']['Form_Type']
                    pan = result['PAN']['PAN']

                    # Build DF column = assessment_year, index name = form_type_val
                    df = build_dataframe(result, assessment_year, form_type_val)

                    temp_results.append(
                        ITRResult(file.name, extracted_rows, result, assessment_year, form_type_val, pan, df)
                    )

                except Exception as e:
                    st.error(f"Error processing {file.name}: {e}")

                progress.progress((idx + 1) / total_files)

            st.session_state.results = temp_results
            st.success("Extraction completed!")

            # Update badges after extraction
            pdf_count, txt_count, xlsx_count, total_count = count_output_files()
            with top_cols[2]:
                st.metric(label="📁 OUTPUT files", value=total_count, delta=f"PDF: {pdf_count} | TXT: {txt_count} | XLSX: {xlsx_count}")

# --- Tabs appear only if we have results in session_state ---
if st.session_state.results:
    tab1, tab2 = st.tabs(["🔍 Preview", "📥 Download & JSON"])

    # --- Tab 1: Preview (filter to show only PDFs or extracted text) ---
    with tab1:
        st.subheader("Preview Files")
        preview_kind = st.radio(
            "Choose what to preview",
            ["Extracted text (.txt)", "Original PDFs (.pdf)"],
            horizontal=True
        )

        if preview_kind == "Extracted text (.txt)":
            extracted_files = list(OUTPUT_DIR.glob("*_extracted.txt"))
            if extracted_files:
                selected_file = st.selectbox("Select a text file to preview", [f.name for f in extracted_files])
                selected_path = OUTPUT_DIR / selected_file
                try:
                    with open(selected_path, "r", encoding="utf-8") as f:
                        full_content = f.read()
                    st.code(full_content, language=None, wrap_lines=False, height=400)
                except FileNotFoundError:
                    st.error(f"File not found: {selected_path}")
            else:
                st.info("No extracted text files available yet.")

        else:  # Original PDFs (.pdf)
            pdf_files = list(OUTPUT_DIR.glob("*.pdf"))
            if pdf_files:
                selected_pdf = st.selectbox("Select a PDF to preview", [p.name for p in pdf_files])
                selected_pdf_path = OUTPUT_DIR / selected_pdf
                try:
                   with pdfplumber.open(selected_pdf_path) as pdf:
                    # Extract text from all pages
                    all_text = ""
                    for page in pdf.pages:
                        page_text = page.extract_text() or ""
                        all_text += page_text + "\n"
                    # Fallback if no text was extracted
                    full_text = all_text if all_text.strip() else "No text extracted from PDF."
                    # Display full text in Streamlit code block
                    st.code(full_text, language=None, wrap_lines=True, height=300)
                   
                except Exception as e:
                    st.warning(f"Preview unavailable: {e}")

                # Allow download of selected PDF
                try:
                    with open(selected_pdf_path, "rb") as f:
                        st.download_button(
                            label=f"📥 Download {selected_pdf}",
                            data=f,
                            file_name=selected_pdf,
                            use_container_width=True,
                        )
                except FileNotFoundError:
                    st.error(f"File not found: {selected_pdf_path}")
            else:
                st.info("No PDF files available in OUTPUT.")

    # --- Tab 2: Group by PAN, Summary table, Download All, per-PAN downloads & JSON ---
    with tab2:
        st.subheader("Summary & Downloads")

        # Build groups
        grouped = defaultdict(list)
        json_grouped = defaultdict(list)
        for r in st.session_state.results:
            grouped[r.pan].append(r.df)
            json_grouped[r.pan].append(r.result)

        # --- Summary table of PANs ---
        summary_rows = []
        for pan, dfs in grouped.items():
            # Collect AYs from each DF's column
            all_ays = []
            for df in dfs:
                all_ays.extend(list(df.columns))
            unique_ays = sorted(set([str(ay) for ay in all_ays]))
            summary_rows.append({
                "PAN": pan,
                "ITR Files": len(dfs),
                "Assessment Years": ", ".join(unique_ays),
            })
        if summary_rows:
            summary_df = pd.DataFrame(summary_rows).sort_values(by=["PAN"])
            st.dataframe(summary_df, use_container_width=True)
        else:
            st.info("No summary available yet.")

        # --- Prepare "Download All" ZIP (build from dataframes in memory) ---
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for pan, dfs in grouped.items():
                combined_df = pd.concat(dfs, axis=1).sort_index(axis=1)
                # Export combined_df to Excel in memory
                xlsx_bytes = io.BytesIO()
                with pd.ExcelWriter(xlsx_bytes, engine="openpyxl") as writer:
                    combined_df.to_excel(writer, sheet_name="ITR")
                xlsx_bytes.seek(0)
                zf.writestr(f"{pan}.xlsx", xlsx_bytes.read())
        zip_buffer.seek(0)

        # --- Download All button ---
        st.download_button(
            label="📦 Download All PAN Excels (ZIP)",
            data=zip_buffer,
            file_name=f"{form_type}_Excels.zip",
            type="primary",
            use_container_width=True,
        )

        st.markdown("---")

        # --- Per-PAN expanders: show combined DF, per-PAN Excel download, JSON ---
        for pan, dfs in grouped.items():
            with st.expander(f"PAN: {pan}", expanded=False):
                combined_df = pd.concat(dfs, axis=1)
                combined_df = combined_df.sort_index(axis=1)

                # Save per-PAN Excel to OUTPUT (optional, supports single-file downloads)
                excel_path = OUTPUT_DIR / f"{pan}.xlsx"
                combined_df.to_excel(excel_path)

                # Show combined DF preview
                st.dataframe(combined_df, use_container_width=True)

                # Per-PAN download button
                with open(excel_path, "rb") as f:
                    st.download_button(
                        label=f"📥 Download Excel for {pan}",
                        data=f,
                        file_name=f"{pan}.xlsx",
                        use_container_width=True,
                    )

                # JSON Preview
                # st.caption("JSON preview for this PAN:")
                # st.json(json_grouped[pan])