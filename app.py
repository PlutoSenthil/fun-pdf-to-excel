
import os
import sys
import io
import glob
import zipfile
import shutil
import streamlit as st

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
    """
    Initialize session_state keys used by the app.
    """
    st.session_state.setdefault("processor", None)
    st.session_state.setdefault("processed", False)
    st.session_state.setdefault("last_config_path", None)
    st.session_state.setdefault("has_preview", False)  # indicates preview is shown

def get_or_create_processor(config_path):
    """
    Create the processor only if it's missing or the config changed.
    """
    if (
        st.session_state.processor is None
        or st.session_state.last_config_path != config_path
    ):
        st.session_state.processor = ITR1BatchProcessor(INPUT_DIR, config_path)
        st.session_state.last_config_path = config_path
        st.session_state.processed = False
        st.session_state.has_preview = False
    return st.session_state.processor

# ----------------- UI ---------------------------------------------
st.set_page_config(page_title="ITR Exporter", page_icon="📄", layout="centered")
st.title("📄 Simple ITR PDF → Excel Exporter")

ensure_session_keys()

# Top utility row: delete INPUT + refresh to clear uploader selection
u1, u2 = st.columns(2)
with u1:
    if st.button("🗑️ Delete INPUT folder (clear all PDFs & Excels)"):
        clear_input_dir()
        st.session_state.processor = None
        st.session_state.processed = False
        st.session_state.has_preview = False
        st.session_state.last_config_path = None
        st.success("INPUT folder cleared.")
        st.rerun()

with u2:
    if st.button("🔄 Refresh (clear upload selection)"):
        st.session_state.processed = False
        st.session_state.has_preview = False
        st.success("Selection cleared.")
        st.rerun()

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
    st.session_state.processed = False
    st.session_state.has_preview = False
    st.success(f"Uploaded {len(uploaded_files)} file(s) into `{INPUT_DIR}`.")

st.divider()

# --- Extract & Preview (with progress bar) + Export button below ---
if st.button("🔍 Extract & Preview"):
    if not config_path:
        st.error("Please select a config (e.g., ITR1).")
    else:
        pbar = st.progress(0, text="Starting extraction...")
        try:
            pbar.progress(30, text="Initializing processor...")
            processor = get_or_create_processor(config_path)

            pbar.progress(60, text="Processing PDFs...")
            processor.process_all()
            st.session_state.processed = True

            pbar.progress(100, text="Extraction complete.")

            # Minimal preview (optional)
            st.subheader("metadata_df")
            metadata_df = processor.metadata()
            st.dataframe(metadata_df, use_container_width=True)
            st.session_state.has_preview = True
        except Exception as e:
            pbar.progress(0)
            st.session_state.has_preview = False
            st.error(f"Extraction failed: {e}")

# Show Export button only if we have a preview or already processed data
if st.session_state.has_preview or st.session_state.processed:
    st.divider()
    st.write("Ready to export the processed data to Excel and download as ZIP:")
    if st.button("📦 Export & Download (ZIP)"):
        pbar = st.progress(0, text="Preparing export...")
        try:
            pbar.progress(20, text="Initializing processor...")
            processor = get_or_create_processor(config_path)

            # (Optional) safeguard: if not processed, process now
            if not st.session_state.processed:
                pbar.progress(40, text="Processing PDFs...")
                processor.process_all()
                st.session_state.processed = True

            pbar.progress(60, text="Exporting Excel by PAN...")
            try:
                processor.export_by_pan()
            except ModuleNotFoundError as e:
                if "xlsxwriter" in str(e):
                    st.error(
                        "Export failed: missing dependency 'xlsxwriter'. "
                        "Run: pip install xlsxwriter\n"
                        "Or modify export_by_pan() to use pandas.ExcelWriter(engine='openpyxl')."
                    )
                    st.stop()
                else:
                    raise

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
