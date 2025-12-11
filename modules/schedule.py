import pandas as pd
import json, os, re
from modules.process_pdf import process_pdf
from modules.extract_logic import clean_row, extract_sections, apply_dynamic_headers


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
            "final_dataframes": {}
        }

        # Load config
        with open(config_path, encoding="utf-8") as f:
            self.config = json.load(f)
        self.debug["config"] = self.config

        # Extract PDF
        self.extracted = process_pdf(input_file, output_file)
        self.debug["raw_extracted"] = self.extracted

    # ---------------------------
    # Utility: store debug values
    # ---------------------------
    def save_debug(self, key, value):
        self.debug[key] = value

    # ---------------------------
    # Utility: slice rows
    # ---------------------------
    def slice_rows(self, start, end):
        return pd.DataFrame(self.extracted[start:end])

class ITR1Sections(PDFPipeline):
    def __init__(self, input_file, output_file, config_path):
        super().__init__(input_file, output_file, config_path)

        # Extract metadata
        self.ack, self.dof, self.pan = self.extract_metadata()
        self.save_debug("metadata", {"ack": self.ack, "dof": self.dof, "pan": self.pan})

        # Build patterns
        self.start_patterns = {k: v["table_start_ptr"] for k, v in self.config.items()}
        self.end_patterns = {k: v["ftr_row_map"] for k, v in self.config.items() if not pd.isna(v["ftr_row_map"])}
        self.hdr_map = {k: v.get("hdr_row_map", ["(1)"]) for k, v in self.config.items()}

        self.save_debug("patterns", {
            "start": self.start_patterns,
            "end": self.end_patterns,
            "hdr_map": self.hdr_map
        })

        # Extract section ranges
        self.sections = extract_sections(self.extracted, self.start_patterns, self.end_patterns, self.hdr_map)
        self.save_debug("section_ranges", self.sections)

        # Build DataFrames
        self.dataframes = self.build_all_sections()

    # ---------------------------
    # Metadata extraction
    # ---------------------------
    def extract_metadata(self):
        ack_pat = re.compile(r"Acknowledgement Number\s*:\s*(\d+).*?Date of Filing\s*:\s*([\w\-]+)", re.I | re.S)
        pan_pat = re.compile(r"\(A1\)\s*PAN\s+(.+?)\s*\(A2\)", re.I | re.S)

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

    # ---------------------------
    # Build all section DataFrames
    # ---------------------------
    def build_all_sections(self):
        dfs = {}
        hdr = ["Acknowledgement", self.ack, "Date of Filing", self.dof, "PAN", self.pan]

        for name, meta in self.sections.items():
            s, e = meta["start"], meta["end"]

            df_raw = self.slice_rows(s, e)
            df_clean = clean_row(df_raw)
            self.debug["cleaned_sections"][name] = df_clean.copy()

            df_final = apply_dynamic_headers(df_clean, self.config, name)
            df_final = self.add_headers(df_final, [name] + hdr)

            dfs[name] = df_final
            self.debug["final_dataframes"][name] = df_final.copy()

        return dfs

    # ---------------------------
    # Add metadata + header row
    # ---------------------------
    @staticmethod
    def add_headers(df, hdr):
        hdr_row = pd.DataFrame([hdr], columns=range(len(hdr)))
        header_row = pd.DataFrame([list(df.columns)], columns=range(len(df.columns)))
        df.columns = range(len(df.columns))
        return pd.concat([hdr_row, header_row, df], ignore_index=True)

    # ---------------------------
    # Public accessor
    # ---------------------------
    def get_section(self, name):
        return self.dataframes.get(name, pd.DataFrame())

class ITR1BatchProcessor:
    def __init__(self, pdf_dir: str, config_path: str):
        self.pdf_dir = pdf_dir
        self.config_path = config_path
        self.results = {}          # ack → ITR1Sections object
        self.errors = {}           # filename → error message

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
            rows.append({
                "ack": ack,
                "pan": itr.pan,
                "dof": itr.dof,
                "sections": list(itr.dataframes.keys()),  # ✅ safe for DataFrame
                "itr_obj": itr                             # ✅ store object, not dict
            })
        df = pd.DataFrame(rows)
        df["dof"] = pd.to_datetime(df["dof"], errors="coerce", dayfirst=True)
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
                            max_len = max(
                                [len(str(col))] +
                                [len(str(val)) for val in final_df[col].values]
                            )
                            worksheet.set_column(idx, idx, max_len + 2)

            print(f"✅ Exported {output_file}")