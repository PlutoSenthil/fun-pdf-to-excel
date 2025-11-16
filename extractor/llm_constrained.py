import json
from typing import Dict, Any, List, Optional

from transformers import AutoTokenizer, AutoModelForCausalLM, pipeline
from pydantic import ValidationError

from lmformatenforcer import JsonSchemaParser
from lmformatenforcer.integrations.transformers import build_transformers_prefix_allowed_tokens_fn

from .schema import TransactionRow

SYSTEM_PROMPT = """You are a meticulous bank statement parser.

Given a SINGLE transaction line (or table row), output EXACTLY ONE JSON object
matching the provided schema.

STRICT RULES:
- Output must be ONE JSON object and NOTHING else.
- Dates MUST be 'DD-MM-YYYY'.
- Numeric fields (debit, credit, balance) MUST be numbers (floats). No null, empty, '-' or currency symbols.
- If a transaction is a debit, set debit>0 and credit=0.0. If a credit, set credit>0 and debit=0.0. If unknown, set both 0.0.
- Exclude headers/totals/metadata. If not a transaction row, still return a valid object with debit=credit=0.0.
""".strip()

def build_user_prompt(page_num: int, line_num: int, line_text: str, header_hint: Optional[str]) -> str:
    hdr = f"\nTABLE HEADER (if present):\n{header_hint}\n" if header_hint else ""
    return (
        f"PAGE: {page_num} | LINE: {line_num}\n"
        f"{hdr}"
        f"LINE TEXT:\n{line_text}\n\n"
        "Return ONLY one JSON object following the schema."
    )

class LMFEConstrained:
    """
    LM-Format-Enforcer + HF Transformers (CPU).
    Forces JSON to match TransactionRow schema at decode-time.
    """
    def __init__(self, model_id: str = "Qwen/Qwen2.5-3B-Instruct", max_new_tokens: int = 350):
        self.model_id = model_id
        self.tokenizer = AutoTokenizer.from_pretrained(model_id, use_fast=True)
        self.model = AutoModelForCausalLM.from_pretrained(
            model_id,
            torch_dtype="auto",
            device_map="cpu",
            low_cpu_mem_usage=True,
        )
        # create text-generation pipeline
        self.pipe = pipeline(
            "text-generation",
            model=self.model,
            tokenizer=self.tokenizer,
            device=-1,
            return_full_text=False,
        )
        # Build JSON Schema from Pydantic
        schema = TransactionRow.model_json_schema()
        self.parser = JsonSchemaParser(schema)
        self.prefix_allowed_tokens_fn = build_transformers_prefix_allowed_tokens_fn(
            self.tokenizer, self.parser
        )
        # detect chat template availability
        self.has_chat_template = hasattr(self.tokenizer, "apply_chat_template") and \
                                 (self.tokenizer.chat_template is not None)

    def _format_messages(self, system_prompt: str, user_prompt: str) -> str:
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        if self.has_chat_template:
            return self.tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        # fallback formatting
        return f"<|system|>\n{system_prompt}\n<|user|>\n{user_prompt}\n<|assistant|>\n"

    def generate_one_row(self, system_prompt: str, user_prompt: str, max_new_tokens: int = 350) -> Dict[str, Any]:
        prompt = self._format_messages(system_prompt, user_prompt)
        out = self.pipe(
            prompt,
            max_new_tokens=max_new_tokens,
            do_sample=False,
            pad_token_id=self.tokenizer.eos_token_id,
            eos_token_id=self.tokenizer.eos_token_id,
            prefix_allowed_tokens_fn=self.prefix_allowed_tokens_fn,  # <-- constrain to schema
        )
        text = out[0]["generated_text"]
        try:
            obj = json.loads(text)
            if not isinstance(obj, dict):
                raise ValueError("Expected a JSON object")
            # final Pydantic validation (should pass due to schema-enforced types)
            _ = TransactionRow(**obj)
            return obj
        except Exception as e:
            raise RuntimeError(f"Structured decode failed: {e}")