import pandas as pd
import json, os, re
from modules.process_pdf import process_pdf
from modules.extract_logic import clean_row, extract_sections, apply_dynamic_headers


class ITR1Sections:
    def __init__(self, input_file: str, output_file: str, config_path: str):

        # ✅ Central debug store
        self.debug = {
            "raw_extracted": None,
            "metadata": {},
            "config": None,
            "patterns": {},
            "section_ranges": None,
            "cleaned_sections": {},
            "final_dataframes": {}
        }

        # ✅ Step 1: Process PDF
        extracted = process_pdf(input_file, output_file)
        self.debug["raw_extracted"] = extracted

        # ✅ Step 2: Extract metadata
        self.ack, self.dof, self.pan = self._extract_metadata(extracted)
        self.debug["metadata"] = {
            "ack": self.ack,
            "dof": self.dof,
            "pan": self.pan
        }

        ack_hdr = ["Acknowledgement", self.ack, "Date of Filing", self.dof, "PAN", self.pan]

        # ✅ Step 3: Load config
        with open(config_path, encoding="utf-8") as f:
            config = json.load(f)
        self.debug["config"] = config

        # ✅ Step 4: Build patterns
        start = {k: v["start_pattern"] for k, v in config.items()}
        end = {k: v["ftr_row_map"] for k, v in config.items() if not pd.isna(v["ftr_row_map"])}
        ack_hdr_map = {k: v.get("hdr_row_map", ["(1)"]) for k, v in config.items()}

        self.debug["patterns"] = {
            "start": start,
            "end": end,
            "hdr_map": ack_hdr_map
        }

        # ✅ Step 5: Extract section ranges
        sections = extract_sections(extracted, start, end, ack_hdr_map)
        self.debug["section_ranges"] = sections

        # ✅ Step 6: Build DataFrames for each section
        self.dataframes = {}

        for name, meta in sections.items():
            s, e = meta["start"], meta["end"]

            # Raw slice
            df_raw = pd.DataFrame(extracted[s:e])

            # Cleaned
            df_clean = clean_row(df_raw)
            self.debug["cleaned_sections"][name] = df_clean.copy()

            # Apply dynamic headers
            df_final = apply_dynamic_headers(df_clean, config, name)

            # Add metadata headers
            df_final = self._add_headers(df_final, [name] + ack_hdr)

            # Store final
            self.dataframes[name] = df_final
            self.debug["final_dataframes"][name] = df_final.copy()

    # ---------------------------------------------------------
    # ✅ Metadata extraction
    # ---------------------------------------------------------
    @staticmethod
    def _extract_metadata(extracted):
        ack_pat = re.compile(r"Acknowledgement Number\s*:\s*(\d+).*?Date of Filing\s*:\s*([\w\-]+)", re.I | re.S)
        pan_pat = re.compile(r"\(A1\)\s*PAN\s+(.+?)\s*\(A2\)", re.I | re.S)

        ack = dof = pan = None

        for row in extracted:
            text = " ".join(str(x) for x in row if x)

            if not ack and (m := ack_pat.search(text)):
                ack, dof = m.group(1).strip(), m.group(2).strip()

            if not pan and (m := pan_pat.search(text)):
                pan = m.group(1).strip()

            if ack and pan:
                break

        return ack, dof, pan

    # ---------------------------------------------------------
    # ✅ Add metadata + header row
    # ---------------------------------------------------------
    @staticmethod
    def _add_headers(df, ack_hdr):
        ack_hdr_row = pd.DataFrame([ack_hdr], columns=range(1, len(ack_hdr) + 1))
        header_row = pd.DataFrame([list(df.columns)], columns=range(1, len(df.columns) + 1))
        df.columns = range(1, len(df.columns) + 1)
        return pd.concat([ack_hdr_row, header_row, df], ignore_index=True)

    # ---------------------------------------------------------
    # ✅ Public accessor
    # ---------------------------------------------------------
    def get_section(self, name: str) -> pd.DataFrame:
        return self.dataframes.get(name, pd.DataFrame())