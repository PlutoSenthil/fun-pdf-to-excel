
import pandas as pd
import json,os,re
from modules.process_pdf import process_pdf
from modules.extract_logic import clean_row,extract_sections,apply_dynamic_headers
class ITR1_SECTIONS:
    def __init__(self, input_file_path: str, output_file_path: str, config_path: str):
        
        self.input_file_path = input_file_path
        self.output_file_path = output_file_path
        self.config_path = config_path

        # Step 1: Process PDF
        self.extracted_data = process_pdf(self.input_file_path, self.output_file_path)

        # Step 2: Load config
        with open(self.config_path, "r", encoding="utf-8") as f:
            self.config = json.load(f)

        # Step 3: Build section prefix mapping
        self.start_pattern = {key: value["start_pattern"] for key, value in self.config.items()}
        self.end_pattern = {key: value["ftr_row_map"] for key, value in self.config.items() if not pd.isna(value["ftr_row_map"])}
        self.hdr_row_map = {key: value.get("hdr_row_map", ["(1)"]) for key, value in self.config.items()}
        
        # Step 4: Extract sections dynamically
        self.sections = extract_sections(self.extracted_data, self.start_pattern,self.end_pattern,self.hdr_row_map)

        # Step 5: Build DataFrames for each section
        self.dataframes = {}
        for section_name, meta in self.sections.items():
            start, end = meta["start"], meta["end"]
            df_temp = pd.DataFrame(self.extracted_data[start:end])
            df_temp = clean_row(df_temp)
            df_temp = apply_dynamic_headers(df_temp, self.config,section_name)
            self.dataframes[section_name] = df_temp
        
        ack_dof_found = False
        pan_found = False
        cols='Acknowledgement_Number'
        self.acknowledgement = None
        ACK_DOF_PATTERN = re.compile(r"Acknowledgement Number\s*:\s*(\d+).*?" r"Date of Filing\s*:\s*([0-9A-Za-z\-]+)(?:\\*)*",re.IGNORECASE | re.DOTALL)
        PAN_PATTERN = re.compile(r"\(A1\)\s*PAN\s+(.+?)\s*\(A2\)", re.IGNORECASE | re.DOTALL)
        for idx, row in enumerate(self.extracted_data):
            row_content_str = " ".join(str(item) for item in row if item is not None)
            # 1. Search for Acknowledgement Number and Date of Filing
            if not ack_dof_found:
                match_ack_dof = ACK_DOF_PATTERN.search(row_content_str)
                if match_ack_dof:
                    self.acknowledgement = match_ack_dof.group(1).strip()
                    self.dof = match_ack_dof.group(2).strip()
                    # self.sections['Acknowledgement_Number'] = {"start": idx, "end": idx + 1}
                    ack_dof_found = True

            # 2. Search for PAN
            if not pan_found:
                match_pan = PAN_PATTERN.search(row_content_str)
                if match_pan:
                    # Note: The pattern (.+?) captures the PAN value
                    self.pan_number = match_pan.group(1).strip()
                    # self.sections['PAN_Number'] = {"start": idx, "end": idx + 1}
                    pan_found = True

            # 3. Check if both are found, then stop iteration
            if ack_dof_found and pan_found:
                break
            
    def get_section(self, section_name: str) -> pd.DataFrame:
        """Return the dataframe for a given section name."""
        return self.dataframes.get(section_name, pd.DataFrame())
    
    def export_to_excel(self, output_excel_path: str) -> str:
        if not self.dataframes:
            return "No dataframes found to export."
        os.makedirs(os.path.dirname(output_excel_path), exist_ok=True)
        
        with pd.ExcelWriter(output_excel_path, engine='xlsxwriter') as writer:
            for sheet_name, df in self.dataframes.items():
                df.to_excel(writer, sheet_name=sheet_name, index=False)
        return f"Successfully exported all sections to **{output_excel_path}**"