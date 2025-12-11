import streamlit as st
import os
from modules.ITR1 import ITR1BatchProcessor  # adjust if your class lives elsewhere (e.g., modules.schedule)

# --- Basic setup ---
INPUT_DIR = "INPUT"
CONFIG_DIR = "config"
os.makedirs(INPUT_DIR, exist_ok=True)
os.makedirs(CONFIG_DIR, exist_ok=True)

def get_config_map():
    """
    Returns { 'ITR1': 'config/ITR1_header.json', ... } for files in config/
    """
    options = {}
    for fname in os.listdir(CONFIG_DIR):
        if fname.lower().endswith("_header.json"):
            key = fname[:-len("_header.json")]  # e.g., 'ITR1'
            options[key] = os.path.join(CONFIG_DIR, fname)
    return options

st.set_page_config(page_title=" Preview (Minimal)", page_icon="📄", layout="centered")
st.title("📄  Metadata Preview (Minimal)")

# --- Config selection ---
config_map = get_config_map()
selected_form = st.selectbox("Select  form", options=sorted(config_map.keys()))
config_path = config_map.get(selected_form)

# --- Upload PDFs to INPUT ---
uploaded_files = st.file_uploader("Upload  PDFs", type=["pdf"], accept_multiple_files=True)
if uploaded_files:
    count = 0
    for f in uploaded_files:
        save_path = os.path.join(INPUT_DIR, f.name)
        with open(save_path, "wb") as out:
            out.write(f.getbuffer())
        count += 1
    st.success(f"Uploaded {count} file(s) into `{INPUT_DIR}`.")

# --- Extract & preview metadata_df ---
if st.button("Extract & Preview"):
    if not config_path:
        st.error("Please select an  config.")
    else:
        processor = ITR1BatchProcessor(INPUT_DIR, config_path)
        processor.process_all()  # no logic change
        metadata_df = processor.metadata()  # your exact call

        st.subheader("Extracted Metadata")
        # Show the full dataframe, or uncomment the next line to show common columns only:
        # st.dataframe(metadata_df[["ack", "pan", "dof", "sections"]])
        st.dataframe(metadata_df)