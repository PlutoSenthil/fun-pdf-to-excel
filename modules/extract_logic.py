import re
import json
import pandas as pd

def clean_int(val):
    try:
        return int(val.strip().replace(',', '').split('.')[0])
    except ValueError:
        return val

def extract_data(extracted_rows, config_path):
    with open(config_path, 'r') as f:
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
            row_content_str = ' '.join(map(str, row))
            if re.search(HEADER_PATTERN, row_content_str, re.IGNORECASE):
                is_in_target_schedule = True
            if is_in_target_schedule:
                match = re.search(PATTERN, row_content_str, re.IGNORECASE)
                if match:
                    field_type = data.get("TYPE", "STRING")
                    if field_type == "NUMERIC" and data.get("EXPECTED_ROW_LEN", 0) == len(row):
                        num_keys = len(KEYS)
                        output = {key: clean_int(row[-(num_keys - i)]) for i, key in enumerate(KEYS)}
                    elif field_type == "NUMERIC" and data.get("EXPECTED_ROW_LEN", 0) != len(row):
                        output = {key: clean_int(match.group(i + 1).strip()) for i, key in enumerate(KEYS)}
                    else:
                        output = {key: match.group(i + 1).strip() for i, key in enumerate(KEYS)}
                    result[data["id"]] = output
                    break
    return result

def build_dataframe(result, assessment_year, form_type):
    data = {}
    for key, value in result.items():
        if isinstance(value, dict):
            # If AMOUNT_CALCULATED exists, use it
            if 'AMOUNT_CALCULATED' in value:
                data[key] = int(str(value['AMOUNT_CALCULATED']).replace(',', ''))
            else:
                # Otherwise take the first value in the dict
                data[key] = list(value.values())[0] if value else None
        else:
            data[key] = value
    df = pd.DataFrame.from_dict(data, orient='index', columns=[assessment_year])
    df.index.name = form_type
    return df