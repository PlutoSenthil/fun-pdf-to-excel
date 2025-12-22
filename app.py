
import os
import sys
import io
import glob
import zipfile
import shutil
import streamlit as st

# --- Ensure project root is on sys.path (no business logic changes) ---
ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# --- Your imports exactly as you stated ---
from modules.ITR1 import ITR1BatchProcessor
# (modules/ITR1.py imports extract_logic itself)

# --- Constants ---
INPUT_DIR = "INPUT"
CONFIG_DIR = "config"
os.makedirs(INPUT_DIR, exist_ok=True)
os.makedirs(CONFIG_DIR, exist_ok=True)

# --- Helpers ---
def get_config_map():
    """Map 'ITR1' -> 'config/ITR1_header.json' for files in config/ ending with '_header.json'."""
    options = {}
    for fname in os.listdir(CONFIG_DIR):
        if fname.lower().endswith("_header.json"):
            key = fname[:-len("_header.json")]  # e.g., 'ITR1'
            options[key] = os.path.join(CONFIG_DIR, fname)
    return options

def zip_excels_in_memory(dir_path):
    """Create an in-memory ZIP of all .xlsx files in dir_path."""
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
    """Delete INPUT folder and recreate it empty."""
    if os.path.isdir(INPUT_DIR):
        shutil.rmtree(INPUT_DIR)
    os.makedirs(INPUT_DIR, exist_ok=True)

# --- UI ---
st.set_page_config(page_title="ITR Exporter", page_icon="📄", layout="centered")
st.title("📄 Simple ITR PDF → Excel Exporter")

# Top utility row: delete INPUT + refresh to clear uploader selection
u1, u2 = st.columns(2)
with u1:
    if st.button("🗑️ Delete INPUT folder (clear all PDFs & Excels)"):
        clear_input_dir()
        st.success("INPUT folder cleared.")
with u2:
    if st.button("🔄 Refresh (clear upload selection)"):
        st.experimental_rerun()

# Config dropdown (simple)
config_map = get_config_map()
selected_form = st.selectbox(
    "Select ITR config",
    options=sorted(config_map.keys()) if config_map else [],
)
config_path = config_map.get(selected_form)

# Upload PDFs (saved into INPUT)
uploaded_files = st.file_uploader("Upload PDFs", type=["pdf"], accept_multiple_files=True)
if uploaded_files:
    for f in uploaded_files:
        save_path = os.path.join(INPUT_DIR, f.name)
        with open(save_path, "wb") as out:
            out.write(f.getbuffer())
    st.success(f"Uploaded {len(uploaded_files)} file(s) into `{INPUT_DIR}`.")

# Keep processor in session (minimal)
if "processor" not in st.session_state:
    st.session_state.processor = None

st.divider()

# --- Extract & Preview (with progress bar) ---
if st.button("🔍 Extract & Preview"):
    if not config_path:
        st.error("Please select a config (e.g., ITR1).")
    else:
        # progress bar (simple / non-intrusive)
        pbar = st.progress(0, text="Starting extraction...")
        try:
            pbar.progress(30, text="Reading PDFs from INPUT...")
            processor = ITR1BatchProcessor(INPUT_DIR, config_path)
            pbar.progress(60, text="Processing all PDFs...")
            processor.process_all()        # ✅ no logic change
            st.session_state.processor = processor
            pbar.progress(100, text="Extraction complete.")

            # Minimal preview (optional)
            metadata_df = processor.metadata()  # ✅ as requested
            st.subheader("metadata_df")
            st.dataframe(metadata_df)
        except Exception as e:
            pbar.progress(0)
            st.error(f"Extraction failed: {e}")

st.divider()

# --- Export & Download (ZIP of Excel) with progress bar ---
if st.button("📦 Export & Download (ZIP)"):
    if not config_path:
        st.error("Please select a config (e.g., ITR1).")
    else:
        pbar = st.progress(0, text="Preparing export...")
        try:
            if st.session_state.processor is None:
                pbar.progress(20, text="Initializing processor...")
                st.session_state.processor = ITR1BatchProcessor(INPUT_DIR, config_path)
                pbar.progress(40, text="Processing PDFs...")
                st.session_state.processor.process_all()

            pbar.progress(60, text="Exporting Excel by PAN...")
            st.session_state.processor.export_by_pan()  # ✅ unchanged

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