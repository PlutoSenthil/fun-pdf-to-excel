import json
from typing import Dict, Any, Optional

from pydantic import ValidationError
from llama_index.llms.openrouter import OpenRouter
from llama_index.core.llms import ChatMessage, MessageRole

from .schema import TransactionRow

try:
    from json_repair import repair_json
except Exception:
    repair_json = None  # optional

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

class OpenRouterLineLLM:
    """
    One-line-in → one JSON object out via OpenRouter (free-tier friendly).
    We keep responses small (line-wise) and validate with Pydantic.
    """
    def __init__(
        self,
        model_id: str = "meta-llama/llama-3.3-70b-instruct:free",
        api_key: Optional[str] = None,
        max_tokens: int = 4096,
        temperature: float = 0.0,
    ):
        # If OPENROUTER_API_KEY env var is set, LlamaIndex will pick it up automatically.
        self.llm = OpenRouter(
            model=model_id,
            api_key=api_key,
            max_tokens=max_tokens,
            temperature=temperature,
        )

    def _extract_json_object(self, text: str) -> Dict[str, Any]:
        """
        Try strict JSON first; otherwise extract {...} substring and optionally repair.
        """
        text = text.strip()
        # fast path
        try:
            obj = json.loads(text)
            if isinstance(obj, dict):
                return obj
        except Exception:
            pass

        # find first '{' .. last '}' window
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            candidate = text[start : end + 1]
            if repair_json is not None:
                candidate = repair_json(candidate, ensure_ascii=False)
            obj = json.loads(candidate)
            if not isinstance(obj, dict):
                raise ValueError("Top-level JSON is not an object")
            return obj

        raise ValueError("No JSON object found in model response.")

    def generate_one_row(self, system_prompt: str, user_prompt: str) -> Dict[str, Any]:
        messages = [
            ChatMessage(role=MessageRole.SYSTEM, content=system_prompt),
            ChatMessage(role=MessageRole.USER, content=user_prompt),
        ]
        resp = self.llm.chat(messages)
        text = resp.message.content

        # Parse JSON; on failure, ask the model once to return JSON-only.
        try:
            obj = self._extract_json_object(text)
        except Exception:
            fix_msgs = [
                ChatMessage(role=MessageRole.SYSTEM, content="Return ONLY one valid JSON object (no prose)."),
                ChatMessage(role=MessageRole.USER, content=text),
            ]
            fix = self.llm.chat(fix_msgs)
            obj = self._extract_json_object(fix.message.content)

        # Pydantic validation (final gate)
        _ = TransactionRow(**obj)
        return obj
