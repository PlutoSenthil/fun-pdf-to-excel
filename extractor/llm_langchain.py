# extractor/llm_langchain.py
import json
from typing import Any, Dict, Optional

from pydantic import ValidationError

from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import JsonOutputParser

from ..schema import TransactionRow

try:
    from json_repair import repair_json
except Exception:
    repair_json = None  # optional fallback

SYSTEM_PROMPT = """You are a meticulous bank statement parser.

Given a SINGLE transaction line (or table row) from a bank statement, return EXACTLY ONE object
matching the provided schema.

STRICT RULES:
- Return only ONE JSON object and NOTHING else (no prose).
- Dates MUST be 'DD-MM-YYYY'.
- Numeric fields (debit, credit, balance) MUST be numbers (floats). No null / empty / '-' / currency symbols.
- If a transaction is a debit, set debit>0 and credit=0.0. If a credit, set credit>0 and debit=0.0. If unknown, set both 0.0.
- Exclude headers, totals, and metadata. If not a transaction line, still return a valid object with debit=credit=0.0.
""".strip()


def get_llm_openrouter(
    model_id: str,
    api_key: str,
    max_tokens: int = 4096,
    temperature: float = 0.0,
    json_mode: bool = False,
) -> ChatOpenAI:
    """
    LangChain OpenAI-compatible client pointing to OpenRouter.
    API base: https://openrouter.ai/api/v1 (OpenAI-style). ①
    """
    params: Dict[str, Any] = dict(
        model=model_id,
        api_key=api_key,
        base_url="https://openrouter.ai/api/v1",
        temperature=temperature,
        max_tokens=max_tokens,
    )
    if json_mode:
        # For models that support native JSON mode via OpenRouter ①
        params["response_format"] = {"type": "json_object"}
    return ChatOpenAI(**params)


def build_user_prompt(page_num: int, line_num: int, line_text: str, header_hint: Optional[str]) -> str:
    hdr = f"\nTABLE HEADER (if present):\n{header_hint}\n" if header_hint else ""
    return (
        f"PAGE: {page_num} | LINE: {line_num}\n"
        f"{hdr}"
        f"LINE TEXT:\n{line_text}\n\n"
        "Return ONLY one JSON object following the schema."
    )


def _extract_json_object(text: str) -> Dict[str, Any]:
    """
    Parse a JSON object from text. Try strict first; otherwise window {...} and repair.
    """
    text = text.strip()
    # Strict
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass

    # Window {...}
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end != -1 and end > start:
        candidate = text[start : end + 1]
        if repair_json is not None:
            candidate = repair_json(candidate, ensure_ascii=False)
        obj = json.loads(candidate)
        if not isinstance(obj, dict):
            raise ValueError("Top-level JSON is not an object")
        return obj

    raise ValueError("No JSON object found in model response.")


def predict_one_row(
    llm: ChatOpenAI,
    page_num: int,
    line_num: int,
    line_text: str,
    header_hint: Optional[str],
    use_structured_first: bool = True,
) -> Dict[str, Any]:
    """
    Preferred: provider-native structured output (with_structured_output) if supported.
    Fallback: JsonOutputParser (langchain-core) with optional json-repair after a retry.
    """
    user_prompt = build_user_prompt(page_num, line_num, line_text, header_hint)

    # 1) Provider-native structured output (supported models)
    if use_structured_first:
        try:
            structured_llm = llm.with_structured_output(TransactionRow)
            obj = structured_llm.invoke([("system", SYSTEM_PROMPT), ("user", user_prompt)])
            return obj.dict()
        except Exception:
            pass

    # 2) Parser strategy
    parser = JsonOutputParser(pydantic_object=TransactionRow)
    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", SYSTEM_PROMPT + "\n{format_instructions}"),
            ("user", "{user_prompt}"),
        ]
    )
    # We call LLM first (so we can repair if needed), then parse
    res = (prompt | llm).invoke(
        {"format_instructions": parser.get_format_instructions(), "user_prompt": user_prompt}
    )

    # Parse attempt
    text = res.content if hasattr(res, "content") else str(res)
    try:
        obj = _extract_json_object(text)
        _ = TransactionRow(**obj)  # final Pydantic check
        return obj
    except Exception:
        # Retry: ask to return JSON-only; then repair if needed
        retry_prompt = ChatPromptTemplate.from_messages(
            [
                ("system", "Return ONLY one valid JSON object (no prose), matching the schema."),
                ("user", "{prev}"),
            ]
        )
        res2 = (retry_prompt | llm).invoke({"prev": text})
        obj = _extract_json_object(res2.content if hasattr(res2, "content") else str(res2))
        _ = TransactionRow(**obj)
        return obj