import json
from typing import List, Dict, Optional

import fitz  # PyMuPDF
import pymupdf4llm
import torch
import pandas as pd

from pydantic import ValidationError
from transformers import AutoTokenizer, AutoModelForCausalLM, pipeline

try:
    from json_repair import repair_json
except Exception:
    repair_json = None

from .schema import FinancialTransactionRow


SYSTEM_PROMPT = """You are a meticulous bank statement parser.

Given ONE PAGE of a bank statement, extract transactions as a JSON array.
Each object must have:
  - date (string, keep original format),
  - reference_or_cheque_no (string or null),
  - description (string),
  - withdrawal_amount (float or null, positive),
  - credit_amount (float or null, positive),
  - balance (float).
Rules:
- Output ONLY a JSON array (no prose).
- No currency symbols; use numbers for amounts.
- Skip headers/footers/totals or any non-transaction text.
"""


def _maybe_enable_layout() -> None:
    """Optionally activate PyMuPDF Layout if available (improves layout & table detection)."""
    try:
        import pymupdf.layout  # noqa: F401
    except Exception:
        pass


def _extract_pages_text(pdf_path: str) -> List[str]:
    """
    Prefer PyMuPDF4LLM page_chunks (layout-aware); fallback to classic text if needed.
    Returns a list of page strings.
    """
    _maybe_enable_layout()
    try:
        data = pymupdf4llm.to_markdown(
            pdf_path,
            page_chunks=True,
            table_strategy="lines_strict",
            show_progress=False,
        )
        pages = []
        for page in data:
            lines = []
            # Tables -> pipe-delimited rows for the LLM
            for tbl in page.get("tables") or []:
                for row in tbl:
                    cells = [(c or "").strip() for c in row]
                    s = " | ".join(cells).strip()
                    if s:
                        lines.append(s)
            # Markdown text
            md = (page.get("text") or "").strip()
            if md:
                lines.extend([ln.strip() for ln in md.splitlines() if ln.strip()])
            # de-dup preserve order
            seen = set()
            merged = []
            for ln in lines:
                if ln not in seen:
                    merged.append(ln)
                    seen.add(ln)
            pages.append("\n".join(merged))
        return pages
    except Exception:
        # Fallback: plain text
        doc = fitz.open(pdf_path)
        pages = []
        for p in doc:
            pages.append((p.get_text("text") or "").strip())
        doc.close()
        return pages


def _load_local_llm(model_name: str) -> pipeline:
    """
    Build a CPU-only text-generation pipeline for a small instruct model.
    Suggested: microsoft/Phi-3-mini-4k-instruct (fast on CPU).
    """
    tok = AutoTokenizer.from_pretrained(model_name, trust_remote_code=True)
    mdl = AutoModelForCausalLM.from_pretrained(
        model_name,
        trust_remote_code=True,
        torch_dtype=torch.float32,
        device_map="cpu",
        low_cpu_mem_usage=True,
    )
    return pipeline("text-generation", model=mdl, tokenizer=tok, device=-1)


def _extract_json(text: str) -> List[Dict]:
    """
    Extract a top-level JSON array from model text; optionally repair slight issues.
    """
    text = text.strip()
    start, end = text.find("["), text.rfind("]")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("No JSON array found.")
    js = text[start:end + 1]
    if repair_json is not None:
        js = repair_json(js, ensure_ascii=False)
    return json.loads(js)


def parse_pdf_to_excel(
    pdf_path: str,
    model_name: str,
    out_path: str,
    max_new_tokens: int = 900,
    temperature: float = 0.0,
) -> pd.DataFrame:
    """
    Page-by-page:
      1) Extract page text (layout-aware if possible)
      2) LLM returns a JSON array of FinancialTransactionRow
      3) Validate with Pydantic and write Excel
    """
    pages = _extract_pages_text(pdf_path)
    llm = _load_local_llm(model_name)

    rows: List[Dict] = []

    for i, page_text in enumerate(pages, start=1):
        prompt = f"{SYSTEM_PROMPT}\n\n--- PAGE {i} START ---\n{page_text}\n--- PAGE {i} END ---\n\nReturn JSON array only."
        out = llm(
            prompt,
            max_new_tokens=max_new_tokens,
            temperature=temperature,
            do_sample=False,
        )[0]["generated_text"]

        try:
            arr = _extract_json(out)
            if not isinstance(arr, list):
                continue
            for obj in arr:
                try:
                    tx = FinancialTransactionRow(**obj)
                    rec = tx.model_dump()
                    rec["page"] = i
                    rows.append(rec)
                except ValidationError:
                    # Skip invalid rows
                    continue
        except Exception:
            # If model drifted and printed prose, just skip that page
            continue

    df = pd.DataFrame(rows)
    # Optional: basic ordering by page to maintain sequence
    if not df.empty:
        df = df.sort_values(["page"]).reset_index(drop=True)
    df.to_excel(out_path, index=False)
