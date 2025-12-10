import re
import json
import pandas as pd
from typing import Dict, List, Any
from functools import reduce
import numpy as np

def clean_int(val):
    try:
        return int(val.strip().replace(",", "").split(".")[0])
    except ValueError:
        return val

def clean_row(df: pd.DataFrame) -> pd.DataFrame:
    df = df.map(lambda x: x.strip() if isinstance(x, str) else x)
    df = df.replace("", np.nan)  # Use np.nan for dropna
    df = df.dropna(axis=1, how="all")  # drop columns full of None
    df = df.dropna(axis=0, how="all")  # drop rows full of None
    temp_df = df.fillna("")
    row_content = temp_df.astype(str).agg(" ".join, axis=1)
    patterns_to_exclude = [
        "If the return is verified after 30 days of transmission",
        "Acknowledgement Number",
    ]
    exclusion_masks = [
        row_content.str.contains(pattern, case=False, regex=True)
        for pattern in patterns_to_exclude
    ]
    combined_exclusion_mask = reduce(np.logical_or, exclusion_masks)
    mask_to_keep = ~combined_exclusion_mask
    df = df[mask_to_keep]
    df = df.dropna(axis=0, how="all")

    return df


def is_empty_row_specific(row):
    if row and row[0] == "":
        return all(v is None for v in row[1:])
    return False


def apply_dynamic_headers(
    df_temp: pd.DataFrame, config: Dict[str, Any], section_name: str
) -> pd.DataFrame:
    section_config = config.get(section_name)
    if not section_config or "table_header" not in section_config:
        return df_temp
    header_map: Dict[str, str] = section_config["table_header"]
    column_labels: List[str] = df_temp.iloc[0].astype(str).tolist()
    new_columns = []
    for label in column_labels:
        new_name = header_map.get(label.strip(), label)
        new_columns.append(new_name)
    df_temp.columns = new_columns
    return df_temp


def extract_sections(data, start_pattern: dict, end_pattern: dict, hdr_row_map: dict):
    sections = {}
    current_section = None
    start_index = None
    total_row = len(data)  # Total number of rows
    EXCLUSION_PATTERNS = {"<empty_row_specific>", ""}

    for idx, row in enumerate(data):
        # row_content_str = " ".join(map(str, row))
        row_content_str = " ".join(str(item) for item in row if item is not None)
        # print(row_content_str)
        # --- 1. Detect Start Pattern Match (Section Name) ---
        if row[0] and isinstance(row[0], str):
            for section_name, start in start_pattern.items():
                if re.search(start, row_content_str, re.IGNORECASE):
                    # print(start[:20],"##",row_content_str[:20])
                    current_section = section_name
                    start_index = None  # reset until we see '(1)' row
                    break

        # --- 2. Detect True Start Index (Row with '(1)') ---
        if current_section and not start_index:
            if row[0] !="" and any(hdr in row for hdr in hdr_row_map.get(current_section,[])):
                # print(row_content_str)
                start_index = idx
                continue  # Skip end-detection for the row that sets start_index

        # --- 3. Detect End of Section ---
        end = end_pattern.get(current_section, None)

        # Determine the section's actual end index (idx + 1, capped at total_row)
        # This is the index *after* the current row (idx)
        section_end_index = min(idx + 1, total_row)

        if current_section and start_index:
            # print(start_index)
            is_end_pattern_match = (
                end
                and end not in EXCLUSION_PATTERNS
                and re.search(end, row_content_str, re.IGNORECASE)
            )

            is_specific_empty_row = (
                end == "<empty_row_specific>" and is_empty_row_specific(row)
            )

            if is_end_pattern_match or is_specific_empty_row:
                sections[current_section] = {
                    "start": start_index,
                    "end": section_end_index,
                }
                current_section = None
                start_index = None

    return sections


def extract_data(extracted_rows, config_path):
    with open(config_path, "r") as f:
        config_data = json.load(f)

    result = {}
    for config_key in config_data.keys():
        data = config_data[config_key]
        result[data["id"]] = {}
        KEYS = data.get("KEYS", [])
        if not KEYS:
            continue
        PATTERN = data.get("PATTERN", "").strip().strip("r'").strip("'")
        HEADER_PATTERN = data.get("HEADER_PATTERN", "").strip().strip("r'").strip("'")
        is_in_target_schedule = False
        for row in extracted_rows:
            row_content_str = " ".join(map(str, row))
            if re.search(HEADER_PATTERN, row_content_str, re.IGNORECASE):
                is_in_target_schedule = True
            if is_in_target_schedule:
                match = re.search(PATTERN, row_content_str, re.IGNORECASE)
                if match:
                    field_type = data.get("TYPE", "STRING")
                    if field_type == "NUMERIC" and data.get(
                        "EXPECTED_ROW_LEN", 0
                    ) == len(row):
                        num_keys = len(KEYS)
                        output = {
                            key: clean_int(row[-(num_keys - i)])
                            for i, key in enumerate(KEYS)
                        }
                    elif field_type == "NUMERIC" and data.get(
                        "EXPECTED_ROW_LEN", 0
                    ) != len(row):
                        output = {
                            key: clean_int(match.group(i + 1).strip())
                            for i, key in enumerate(KEYS)
                        }
                    else:
                        output = {
                            key: match.group(i + 1).strip()
                            for i, key in enumerate(KEYS)
                        }
                    result[data["id"]] = output
                    break
    return result


def build_dataframe(result, assessment_year, form_type):
    data = {}
    for key, value in result.items():
        if isinstance(value, dict):
            # If AMOUNT_CALCULATED exists, use it
            if "AMOUNT_CALCULATED" in value:
                data[key] = int(str(value["AMOUNT_CALCULATED"]).replace(",", ""))
            else:
                # Otherwise take the first value in the dict
                data[key] = list(value.values())[0] if value else None
        else:
            data[key] = value
    df = pd.DataFrame.from_dict(data, orient="index", columns=[assessment_year])
    df.index.name = form_type
    return df