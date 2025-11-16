import fitz
import pymupdf4llm
import torch
from transformers import AutoTokenizer, AutoModelForCausalLM, pipeline
from pydantic import ValidationError
import pandas as pd
from typing import List, Dict
from extractor.schema import FinancialTransactionRow

SYSTEM_PROMPT = """You are a meticulous bank statement parser.
Return ONLY a JSON array of transaction objects matching this schema:
date, reference_or_cheque_no, description, withdrawal_amount, credit_amount, balance.
Rules:
- Dates as seen (original format).
- Numeric fields must be floats (no currency symbols).
- If missing, use null.
- Output ONLY JSON array, no extra text.
"""

def extract_pages(pdf_path: str) -> List[str]:
    doc = fitz.open(pdf_path)
    pages = []
    for page in doc:
        text = page.get_text("text")
        pages.append(text.strip())
    doc.close()
    return pages

def load_local_llm(model_name: str = "microsoft/Phi-3-mini-4k-instruct"):
    tokenizer = AutoTokenizer.from_pretrained(model_name)
    model = AutoModelForCausalLM.from_pretrained(model_name, device_map="cpu", torch_dtype=torch.float32)
    return pipeline("text-generation", model=model, tokenizer=tokenizer, device=-1)

def parse_pdf_to_excel(pdf_path: str, model_name: str, out_path: str):
    pages = extract_pages(pdf_path)
    llm = load_local_llm(model_name)
    all_rows: List[Dict] = []

    for i, page_text in enumerate(pages, start=1):
        prompt = f"{SYSTEM_PROMPT}\n\nPAGE {i}:\n{page_text}\n\nReturn JSON array only."
        output = llm(prompt, max_new_tokens=800, temperature=0.0)[0]["generated_text"]

        # Extract JSON array
        start, end = output.find("["), output.rfind("]")
        if start == -1 or end == -1:
            continue
        json_str = output[start:end+1]

        import json
        try:
            data = json.loads(json_str)
            for item in data:
                try:
                    row = FinancialTransactionRow(**item)
                    rec = row.model_dump()
                    rec["page"] = i
                    all_rows.append(rec)
                except ValidationError:
                    continue
        except Exception:
            continue

    df = pd.DataFrame(all_rows)
    df.to_excel(out_path, index=False)
    return df