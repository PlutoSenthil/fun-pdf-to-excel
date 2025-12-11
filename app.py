
import os
import sys
import streamlit as st

# --- Ensure project root is on sys.path (does not change any business logic) ---
ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# --- Your imports exactly as you stated ---
from modules.ITR1 import ITR1BatchProcessor
# (No need to import extract_logic here; ITR1.py already imports it)

# --- Constants ---
INPUT_DIR = "INPUT"
CONFIG_DIR = "config"

os.makedirs(INPUT_DIR, exist_ok=True)
os.makedirs(CONFIG_DIR, exist_ok=True)

def get_config_map():
    """Map 'ITR1' -> 'config/ITR1_header.json' for files in config/ ending with '_header.json'."""
    options = {}
    for fname in os.listdir(CONFIG_DIR):
        if fname.lower().endswith("_header.json"):
            key = fname[:-len("_header.json")]  # e.g., 'ITR1'
            options[key] = os.path.join(CONFIG_DIR, fname)
    return options

# --- UI ---
st.set_page_config(page_title=" Metadata Preview", page_icon="📄", layout="centered")
st.title("📄  Metadata Preview (Minimal)")

# Config dropdown (kept simple)
config_map = get_config_map()
selected_form = st.selectbox(
    "Select  form",
    options=sorted(config_map.keys()) if config_map else [],
)
config_path = config_map.get(selected_form)

# Upload PDFs (saved into INPUT)
uploaded_files = st.file_uploader("Upload  PDFs", type=["pdf"], accept_multiple_files=True)
if uploaded_files:
    for f in uploaded_files:
        save_path = os.path.join(INPUT_DIR, f.name)
        with open(save_path, "wb") as out:
            out.write(f.getbuffer())
    st.success(f"Uploaded {len(uploaded_files)} file(s) into `{INPUT_DIR}`.")

# Extract + Preview
if st.button("Extract & Preview"):
    if not config_path:
        st.error("Please select a config (e.g., ITR1_header.json).")
    else:
        # No logic changes: run the same processor calls you use
        processor = ITR1BatchProcessor(INPUT_DIR, config_path)
        processor.process_all()
        metadata_df = processor.metadata()

        st.subheader("metadata_df")
       
