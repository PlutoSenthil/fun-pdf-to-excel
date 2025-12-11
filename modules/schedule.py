import pandas as pd
import json, os, re
from modules.process_pdf import process_pdf
from modules.extract_logic import clean_row, extract_sections, apply_dynamic_headers


class ITR1Sections:
    def __init__(self, input_file: str, output_file: str, config_path: str):
        # Process PDF
        extracted = process_pdf(input_file, output_file)

        # Extract metadata
        self.ack, self.dof, self.pan = self._extract_metadata(extracted)
        hdr = ["Acknowledgement",self.ack,"Date of Filing",self.dof,"PAN",self.pan]

        # Load config
        with open(config_path, encoding="utf-8") as f:
            config = json.load(f)

        # Build patterns
        start = {k: v["start_pattern"] for k, v in config.items()}
        end = {k: v["ftr_row_map"] for k, v in config.items() if not pd.isna(v["ftr_row_map"])}
        hdr_map = {k: v.get("hdr_row_map", ["(1)"]) for k, v in config.items()}

        # Extract sections → DataFrames
        self.dataframes = {
            name: self._add_headers(
                apply_dynamic_headers(clean_row(pd.DataFrame(extracted[s:e])), config, name),
                hdr
            )
            for name, meta in extract_sections(extracted, start, end, hdr_map).items()
            for s, e in [(meta["start"], meta["end"])]
        }

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
            if ack and pan: break
        return ack, dof, pan

    @staticmethod
    def _add_headers(df, hdr):
        # prepend metadata + header row
        hdr_row = pd.DataFrame([hdr], columns=range(len(hdr)))
        header_row = pd.DataFrame([list(df.columns)], columns=range(len(df.columns)))
        df.columns = range(len(df.columns))
        return pd.concat([hdr_row, header_row, df], ignore_index=True)

    def get_section(self, name: str) -> pd.DataFrame:
        return self.dataframes.get(name, pd.DataFrame())