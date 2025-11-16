from typing import List, Optional, Dict, Any, Type
import math
import pandas as pd
from pydantic import ValidationError

from ..schema import FinancialTransactionRow
from .layout_extract import extract_lines_pymupdf4llm
from .gemini_client import build_gemini_client, extract_batch_with_schema

SYSTEM_INSTRUCTIONS = """You are a meticulous parser of bank statements.

You will receive one or more transaction lines from a single page. For each
true transaction line, produce one JSON object matching the schema.
If a line is not a transaction row (headers/totals/footers), skip it.

Rules:
- Keep the date string as seen (no reformatting).
- Numeric fields must be numbers (floats). Do not emit currency symbols or '-'.
- If an amount is absent, use null.
- 'withdrawal_amount' and 'credit_amount' must be positive numbers.
- 'balance' must be a number.
"""

def batch(iterable: List[str], n: int) -> List[List[str]]:
    return [iterable[i:i+n] for i in range(0, len(iterable), n)]

def pdf_to_excel_batched(
    pdf_path: str,
    out_xlsx_path: str,
    google_api_key: str,
    model_id: str,
    batch_size: int = 8,          # N lines per call for speed
    max_output_tokens: int = 2048,
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

    client = build_gemini_client(google_api_key)

    records: List[Dict[str, Any]] = []

    for page_idx, (lines, header_hint) in enumerate(zip(pages_lines, header_hints), start=1):
        # quick filter to cut obvious non-rows
        if skip_non_txn_filter:
            filtered = []
            for ln in lines:
                has_amountish = any(ch.isdigit() for ch in ln) and ('.' in ln or ',' in ln)
                has_dateish = ('-' in ln or '/' in ln)
                if has_amountish or has_dateish:
                    filtered.append(ln)
            lines = filtered

        for chunk in batch(lines, batch_size):
            if not chunk:
                continue
            # Build prompt per batch; add header hint to guide mapping
            header_part = f"\nKnown header: {header_hint}\n" if header_hint else ""
            prompt = SYSTEM_INSTRUCTIONS + header_part + "\nLines:\n"

            try:
                parsed = extract_batch_with_schema(
                    client=client,
                    model_id=model_id,
                    prompt=prompt,
                    batch_lines=chunk,
                    schema=list[FinancialTransactionRow],  # type: ignore  (PEP 695)
                    max_output_tokens=max_output_tokens,
                )
                # parsed is List[FinancialTransactionRow]
                for obj in parsed:
                    try:
                        row = FinancialTransactionRow.model_validate(obj)
                        rec = row.model_dump()
                        rec["page"] = page_idx
                        records.append(rec)
                    except ValidationError as ve:
                        error_log.append(f"[Page {page_idx}] pydantic error: {ve}")
            except Exception as e:
                error_log.append(f"[Page {page_idx}] Gemini error: {e}")

    df = pd.DataFrame(records)

    # Optional sort: date as text preserved; sort by page to keep chronological context
    if not df.empty:
        df = df.sort_values(["page"]).reset_index(drop=True)

    df.to_excel(out_xlsx_path, index=False)
    return df