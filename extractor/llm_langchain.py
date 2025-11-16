import json
from typing import Any, Dict, Optional

from pydantic import ValidationError

from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import JsonOutputParser
from langchain.output_parsers import OutputFixingParser

from .schema import TransactionRow

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
    OpenRouter base is https://openrouter.ai/api/v1 (OpenAI style). ②
    """
    params: Dict[str, Any] = dict(
        model=model_id,
        api_key=api_key,
        base_url="https://openrouter.ai/api/v1",
        temperature=temperature,
        max_tokens=max_tokens,
    )
    if json_mode:
        # For models that support native JSON mode via OpenRouter
        # (OpenRouter honors response_format for eligible models) ②
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


def predict_one_row(
    llm: ChatOpenAI,
    page_num: int,
    line_num: int,
    line_text: str,
    header_hint: Optional[str],
    use_structured_first: bool = True,
) -> Dict[str, Any]:
    """
    Try provider-native structured output (with_structured_output) first.
    Fallback: JsonOutputParser + OutputFixingParser (LangChain built-ins).
    """
    user_prompt = build_user_prompt(page_num, line_num, line_text, header_hint)

    # 1) Preferred: provider-native structured output (if supported by the model)
    if use_structured_first:
        try:
            structured_llm = llm.with_structured_output(TransactionRow)
            obj = structured_llm.invoke(
                [
                    ("system", SYSTEM_PROMPT),
                    ("user", user_prompt),
                ]
            )
            # obj is a Pydantic model instance; cast to dict
            return obj.dict()
        except Exception:
            # fall through to parser strategy
            pass

    # 2) Parser strategy with auto-fix
    parser = JsonOutputParser(pydantic_object=TransactionRow)
    fix_parser = OutputFixingParser.from_llm(parser=parser, llm=llm)
    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", SYSTEM_PROMPT + "\n{format_instructions}"),
            ("user", "{user_prompt}"),
        ]
    )
    chain = prompt | llm | fix_parser
    result = chain.invoke(
        {"format_instructions": parser.get_format_instructions(), "user_prompt": user_prompt}
    )

    # result is dict validated by parser; ensure Pydantic validation one more time
    _ = TransactionRow(**result)
    return result