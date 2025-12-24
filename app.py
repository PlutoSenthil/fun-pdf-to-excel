import os
import sys
import io
import glob
import zipfile
import shutil
import streamlit as st
import logging
logging.getLogger('pdfminer.pdfinterp').setLevel(logging.ERROR)
logging.getLogger('pdfminer.layout').setLevel(logging.ERROR)

# ----------------- Ensure project root on sys.path -----------------
ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# ----------------- Your business logic import ---------------------
from modules.ITR1 import ITR1BatchProcessor

# ----------------- Constants --------------------------------------
INPUT_DIR = "INPUT"
CONFIG_DIR = "config"
os.makedirs(INPUT_DIR, exist_ok=True)
os.makedirs(CONFIG_DIR, exist_ok=True)

# ----------------- Helpers ----------------------------------------
def get_config_map():
    """
    Map 'ITR1' -> 'config/ITR1_header.json' for files in config/ ending with '_header.json'.
    """
    options = {}
    for fname in os.listdir(CONFIG_DIR):
        if fname.lower().endswith("_header.json"):
            key = fname[:-len("_header.json")]  # e.g., 'ITR1'
            options[key] = os.path.join(CONFIG_DIR, fname)
    return options

def zip_excels_in_memory(dir_path):
    """
    Create an in-memory ZIP of all .xlsx files in dir_path.
    Returns (bytes_or_None, count).
    """
    files = sorted(glob.glob(os.path.join(dir_path, "*.xlsx")))
    if not files:
        return None, 0
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for fp in files:
            zf.write(fp, arcname=os.path.basename(fp))
    buf.seek(0)
    return buf.getvalue(), len(files)

def clear_input_dir():
    """
    Delete INPUT folder and recreate it empty.
    """
    if os.path.isdir(INPUT_DIR):
        shutil.rmtree(INPUT_DIR)
    os.makedirs(INPUT_DIR, exist_ok=True)

def ensure_session_keys():
    if "uploader_key" not in st.session_state:
        st.session_state.uploader_key = 0

def reset_uploader():
    st.session_state.uploader_key += 1
    clear_input_dir()

# ----------------- UI ---------------------------------------------
st.set_page_config(page_title="ITR Exporter", layout="centered")
st.title("📄 Simple ITR PDF → Excel Exporter")

ensure_session_keys()

st.button("🔄 Refresh", on_click=reset_uploader)
# st.rerun()

# Config dropdown (simple)
config_map = get_config_map()
selected_form = st.selectbox(
    "Select ITR config",
    options=sorted(config_map.keys()) if config_map else [],
)
config_path = config_map.get(selected_form)

# Upload PDFs (saved into INPUT)
uploaded_files = st.file_uploader("Upload PDFs", type=["pdf"], 
            accept_multiple_files=True,
            key=f"pdf_uploader_{st.session_state.uploader_key}")
if uploaded_files:
    for f in uploaded_files:
        save_path = os.path.join(INPUT_DIR, f.name)
        with open(save_path, "wb") as out:
            out.write(f.getbuffer())
    st.success(f"Uploaded {len(uploaded_files)} file(s) into `{INPUT_DIR}`.")

st.divider()

# --- Export & Download (ZIP of Excel) with progress bar ---
if st.button("📦 Export & Download (ZIP)"):
    if not config_path:
        st.error("Please select a config (e.g., ITR1).")
    else:
        pbar = st.progress(0, text="Preparing export...")
        try:
            pbar.progress(20, text="Initializing processor...")
            processor = ITR1BatchProcessor(INPUT_DIR, config_path)

            pbar.progress(40, text="Processing PDFs...")
            processor.process_all()
                        
            # Minimal preview (optional)
            pbar.progress(50, text="metadata_df")
            metadata_df = processor.metadata()
            st.dataframe(metadata_df)

            pbar.progress(60, text="Exporting Excel by PAN...")
            processor.export_by_pan()

            pbar.progress(80, text="Building ZIP...")
            zip_bytes, count = zip_excels_in_memory(INPUT_DIR)

            if not zip_bytes or count == 0:
                pbar.progress(0)
                st.warning("No Excel files found after export.")
            else:
                pbar.progress(100, text="ZIP ready.")
                st.success(f"Prepared {count} Excel file(s) for download.")
                st.download_button(
                    label="⬇️ Download Excel ZIP",
                    data=zip_bytes,
                    file_name="ITR_by_PAN.zip",
                    mime="application/zip",
                )
        except Exception as e:
            pbar.progress(0)
            st.error(f"Export failed: {e}")