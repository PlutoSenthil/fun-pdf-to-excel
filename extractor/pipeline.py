import pandas as pd
from typing import Optional, List, Dict, Any
from pydantic import ValidationError

from .schema import TransactionRow
from .layout_extract import extract_lines_pymupdf4llm
from .llm_openrouter import OpenRouterLineLLM, SYSTEM_PROMPT, build_user_prompt

def pdf_to_excel_linewise(
    pdf_path: str,
    out_xlsx_path: str,
    model_id: str = "meta-llama/llama-3.3-70b-instruct:free",
    api_key: Optional[str] = None,
    max_tokens: int = 4096,
    temperature: float = 0.0,
    use_layout: bool = True,
    skip_non_txn_filter: bool = True,
    error_log: Optional[List[str]] = None,
) -> pd.DataFrame:
    if error_log is None:
        error_log = []

    pages_lines, header_hints = extract_lines_pymupdf4llm(
        pdf_path=pdf_path,
        use_layout=use_layout,
        table_strategy="lines_strict",
        page_chunks=True,
    )

    llm = OpenRouterLineLLM(
        model_id=model_id,
        api_key=api_key,
        max_tokens=max_tokens,
        temperature=temperature,
    )

    records: List[Dict[str, Any]] = []

    for page_idx, (lines, header_hint) in enumerate(zip(pages_lines, header_hints), start=1):
        page_count = 0
        for line_idx, line in enumerate(lines, start=1):
            if skip_non_txn_filter:
                has_amountish = any(ch.isdigit() for ch in line) and ('.' in line or ',' in line)
                has_dateish = ('-' in line or '/' in line)
                if not (has_amountish or has_dateish):
                    continue

            user_prompt = build_user_prompt(page_idx, line_idx, line, header_hint)
            try:
                obj = llm.generate_one_row(SYSTEM_PROMPT, user_prompt)
                row = TransactionRow(**obj)
                rec = row.model_dump()
                rec["page"] = page_idx
                rec["line_index"] = line_idx
                records.append(rec)
                page_count += 1
            except ValidationError as ve:
                error_log.append(f"[Page {page_idx} Line {line_idx}] pydantic error: {ve}")
            except Exception as e:
                error_log.append(f"[Page {page_idx} Line {line_idx}] LLM error: {e}")

    df = pd.DataFrame(records)

    def dmy_key(s: str):
        try:
            d, m, y = s.split("-")
            return (int(y), int(m), int(d))
        except Exception:
            return (9999, 12, 31)

    if not df.empty:
        df["__sv"] = df["value_date"].map(dmy_key)
        df["__sp"] = df["post_date"].map(dmy_key)
        df = df.sort_values(["__sv", "__sp", "page", "line_index"]).drop(columns=["__sv", "__sp"], errors="ignore")

    df.to_excel(out_xlsx_path, index=False)
    return df