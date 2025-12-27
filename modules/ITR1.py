from modules.process_pdf import process_pdf
from modules.helper import clean_and_prepend_none,apply_dynamic_headers,is_empty_row_specific,clean_row
import pandas as pd
import json,re,os

class PDFPipeline:
    def __init__(self, input_file, output_file, config_path):
        self.input_file = input_file
        self.output_file = output_file
        self.config_path = config_path

        # Central debug store
        self.debug = {
            "raw_extracted": None,
            "metadata": {},
            "config": None,
            "patterns": {},
            "section_ranges": None,
            "cleaned_sections": {},
            "final_dataframes": {},
            "extract_sections_log": [],
        }

        # Load config
        with open(config_path, encoding="utf-8") as f:
            self.config = json.load(f)
        self.debug["config"] = self.config

        # Extract PDF
        self.extracted = process_pdf(input_file, output_file)
        self.debug["raw_extracted"] = self.extracted

    def save_debug(self, key, value):
        self.debug[key] = value

    def slice_rows(self, start, end, indentation_skip=None):
        if indentation_skip:
            cleaned = clean_and_prepend_none(self.extracted[start:end], indentation_skip)
            return pd.DataFrame(cleaned)
        return pd.DataFrame(self.extracted[start:end])

class ITR1Sections(PDFPipeline):
    def __init__(self, input_file, output_file, config_path):
        super().__init__(input_file, output_file, config_path)

        # Extract metadata
        self.ack, self.dof, self.pan = self.extract_metadata()
        self.save_debug("metadata", {"ack": self.ack, "dof": self.dof, "pan": self.pan})
        

        # Build patterns
        self.table_start_ptr = {k: v.get("table_start_ptr") for k, v in self.config.items()}
        self.ftr_row_map = {k: v.get("ftr_row_map") for k, v in self.config.items()}
        self.hdr_map = {k: v.get("hdr_row_map") for k, v in self.config.items()}
        self.indentation_skip = {k: v.get("indentation_skip") for k, v in self.config.items()}

        self.save_debug("patterns", {
            "start": self.table_start_ptr,
            "end": self.ftr_row_map,
            "hdr_map": self.hdr_map,
            "indentation_skip": self.indentation_skip,
        })

        # Extract sections WITH DEBUG
        self.sections = self.extract_sections(
            self.extracted,
            self.table_start_ptr,
            self.ftr_row_map,
            self.hdr_map
        )
        self.save_debug("section_ranges", self.sections)

        # Build DataFrames
        self.dataframes = self.build_all_sections()

    # ---------------------------------------------------------
    # ✅ Metadata extraction
    # ---------------------------------------------------------
    def extract_metadata(self):
        ack_pat = re.compile(
            r"Acknowledgement Number\s*:\s*(\d+).*?Date of Filing\s*:\s*([\w\-]+)",
            re.I | re.S,
        )
        # pan_pat = re.compile(r"\(A1\)\s*PAN\s+(.+?)\s*\(A2\)", re.I | re.S)
        pan_pat = re.compile(r"PAN\s*([A-Z0-9]{10})", re.I)
        ack = dof = pan = None

        for row in self.extracted:
            text = " ".join(str(x) for x in row if x)

            if not ack and (m := ack_pat.search(text)):
                ack, dof = m.group(1).strip(), m.group(2).strip()

            if not pan and (m := pan_pat.search(text)):
                pan = m.group(1).strip()

            if ack and pan:
                break

        return ack, dof, pan

    # ---------------------------------------------------------
    # ✅ Section extraction with FULL DEBUG
    # ---------------------------------------------------------
    def extract_sections(self, data, start_pattern, end_pattern, hdr_row_map):
        sections = {}
        current_section = None
        start_index = None
        total_row = len(data)

        for idx, row in enumerate(data):
            row_str = " ".join(str(x) for x in row if x)

            # --- Start Pattern ---
            for sec, pat in start_pattern.items():
                if pat and re.search(pat, row_str, re.IGNORECASE):
                    self.debug["extract_sections_log"].append(
                        {"row": idx, "section": sec, "event": "start_match", "text": row_str}
                    )
                    current_section = sec
                    start_index = None
                    break

            # --- Header Row ---
            if current_section and not start_index:
                hdrs = hdr_row_map.get(current_section, [])
                if row and row[0] != "" and any(h in row for h in hdrs):
                    start_index = idx
                    self.debug["extract_sections_log"].append(
                        {"row": idx, "section": current_section, "event": "header_match", "text": row_str}
                    )
                    continue

            # --- End Pattern ---
            if current_section and start_index:
                end_pat = end_pattern.get(current_section)
                is_end = False

                if end_pat and end_pat not in ["", "<empty_row_specific>"]:
                    if re.search(end_pat, row_str, re.IGNORECASE):
                        is_end = True
                        self.debug["extract_sections_log"].append(
                            {"row": idx, "section": current_section, "event": "end_match", "text": row_str}
                        )

                if end_pat == "<empty_row_specific>" and is_empty_row_specific(row):
                    is_end = True
                    self.debug["extract_sections_log"].append(
                        {"row": idx, "section": current_section, "event": "empty_row_match", "text": row_str}
                    )

                if is_end:
                    sections[current_section] = {"start": start_index, "end": idx + 1}
                    self.debug["extract_sections_log"].append(
                        {"row": idx, "section": current_section, "event": "section_completed"}
                    )
                    current_section = None
                    start_index = None

        return sections

    # ---------------------------------------------------------
    # ✅ Build all section DataFrames
    # ---------------------------------------------------------
    def build_all_sections(self):
        dfs = {}
        hdr = [ "Date of Filing: "+str(self.dof),"Acknowledgement: "+str(self.ack), "PAN: "+str(self.pan)]

        for name, meta in self.sections.items():
            start, end = meta["start"], meta["end"]
            indent = self.indentation_skip.get(name)

            df_raw = self.slice_rows(start, end, indent)
            df_clean = clean_row(df_raw)
            self.debug["cleaned_sections"][name] = df_clean.copy()

            df_final = apply_dynamic_headers(df_clean, self.config, name)
            df_final = self.add_headers(df_final, [name] + hdr)

            dfs[name] = df_final
            self.debug["final_dataframes"][name] = df_final.copy()

        return dfs

    # ---------------------------------------------------------
    # ✅ Add metadata + header row
    # ---------------------------------------------------------
    @staticmethod
    def add_headers(df, hdr):
        hdr_row = pd.DataFrame([hdr], columns=range(len(hdr)))
        header_row = pd.DataFrame([list(df.columns)], columns=range(len(df.columns)))
        df.columns = range(len(df.columns))
        return pd.concat([hdr_row, header_row, df], ignore_index=True)

    # ---------------------------------------------------------
    # ✅ Public accessor
    # ---------------------------------------------------------
    def get_section(self, name):
        return self.dataframes.get(name, pd.DataFrame())

    # ---------------------------------------------------------
    # ✅ Single-file Excel export
    # ---------------------------------------------------------
    def export_to_excel(self, output_file):
        with pd.ExcelWriter(output_file, engine="xlsxwriter") as writer:
            for name, df in self.dataframes.items():
                df.to_excel(writer, sheet_name=name, index=False)
                ws = writer.sheets[name]
                for col in range(len(df.columns)):
                        max_len = max(len(str(x)) for x in df[col])
                        ws.set_column(col, col, max(max_len + 2,60))    

    def debug_viewer(self):
        return ExtractionDebugViewer(self.debug.get("extract_sections_log", []))
    
class ITR1BatchProcessor:
    def __init__(self, pdf_dir: str, config_path: str):
        self.pdf_dir = pdf_dir
        self.config_path = config_path
        self.results = {}  # ack → ITR1Sections object
        self.errors = {}  # filename → error message

    # ---------------------------------------------------------
    # ✅ Process all PDFs in directory
    # ---------------------------------------------------------
    def process_all(self):
        pdfs = [f for f in os.listdir(self.pdf_dir) if f.lower().endswith(".pdf")]

        for pdf in pdfs:
            input_file = os.path.join(self.pdf_dir, pdf)
            output_file = input_file.replace(".pdf", "_extracted.txt")

            try:
                itr = ITR1Sections(input_file, output_file, self.config_path)
                key = itr.ack or pdf
                self.results[key] = itr
            except Exception as e:
                self.errors[pdf] = str(e)

        return self.results

    # ---------------------------------------------------------
    # ✅ Clean metadata DataFrame (no nested dicts)
    # ---------------------------------------------------------
    def metadata(self):
        rows = []
        for ack, itr in self.results.items():
            rows.append(
                {
                    "ack": ack,
                    "pan": itr.pan,
                    "dof": itr.dof,
                    "sections": list(itr.dataframes.keys()),  # ✅ safe for DataFrame
                    "itr_obj": itr,  # ✅ store object, not dict
                }
            )
        df = pd.DataFrame(rows)
        df["dof"] = pd.to_datetime(df["dof"], errors="coerce", dayfirst=True).dt.date
        df = df.sort_values(by=["pan", "dof"], ascending=[True, True])
        return df

    # ---------------------------------------------------------
    # ✅ Export grouped Excel by PAN
    # ---------------------------------------------------------
    def export_by_pan(self, output_dir=None):
        if output_dir is None:
            output_dir = self.pdf_dir

        df = self.metadata()

        with open(self.config_path, encoding="utf-8") as f:
            config = json.load(f)

        for pan, group in df.groupby("pan"):
            group_sorted = group.sort_values("dof")
            output_file = os.path.join(output_dir, f"{pan}.xlsx")

            with pd.ExcelWriter(output_file, engine="xlsxwriter") as writer:
                for section in config.keys():
                    dfs = []
                    for _, row in group_sorted.iterrows():
                        itr = row["itr_obj"]
                        if section in itr.dataframes:
                            df_sec = itr.dataframes[section].copy()
                            df_sec.loc[len(df_sec)] = [pd.NA] * len(df_sec.columns)
                            dfs.append(df_sec)

                    if dfs:
                        final_df = pd.concat(dfs, ignore_index=True)
                        final_df.to_excel(writer, sheet_name=section, index=False)

                        # Auto column width
                        worksheet = writer.sheets[section]
                        for idx, col in enumerate(final_df.columns):
                            column_data_max = final_df[col].astype(str).str.len().max()
                            max_len = max(len(str(col)), column_data_max)
                            worksheet.set_column(idx, idx,min(max_len + 2,60))

            print(f"✅ Exported {output_file}")



class ExtractionDebugViewer:
    def __init__(self, log):
        self.log = log
        self.df = pd.DataFrame(log) if log else pd.DataFrame(columns=["row", "section", "event", "text"])

    def show(self, max_rows=50):
        pd.set_option("display.max_colwidth", 200)
        return self.df.head(max_rows)

    def by_section(self, section):
        pd.set_option("display.max_colwidth", 200)
        return self.df[self.df["section"] == section].copy()

    def by_event(self, event):
        pd.set_option("display.max_colwidth", 200)
        return self.df[self.df["event"] == event].copy()

    def failures(self):
        # typical “interesting” events: start_match & header_match without corresponding section_completed
        pd.set_option("display.max_colwidth", 200)
        return self.df[self.df["event"].isin(["start_match", "header_match"])].copy()

    def print(self, limit=100):
        subset = self.df.head(limit).to_dict("records")
        for row in subset:
            print(f"[{row['event']}] Row {row['row']} | Section: {row['section']}")
            print(f"   → {str(row['text'])[:200]}")
            print("-" * 80)