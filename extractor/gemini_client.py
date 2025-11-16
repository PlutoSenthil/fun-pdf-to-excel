from typing import List, Type, Any
from pydantic import BaseModel

from google import genai
from google.genai import types

def build_gemini_client(google_api_key: str) -> genai.Client:
    # The new google-genai SDK creates a single Client.
    return genai.Client(api_key=google_api_key)

def extract_batch_with_schema(
    client: genai.Client,
    model_id: str,
    prompt: str,
    batch_lines: List[str],
    schema: Any,  # Pydantic model (e.g., list[FinancialTransactionRow]) or JSON schema dict
    max_output_tokens: int = 2048,
):
    """
    Sends a batched chunk of lines and returns parsed structured data.

    The SDK enforces schema when response_mime_type='application/json' AND
    response_schema=<Pydantic or JSON schema>. Use .parsed for typed results.
    """
    joined = "\n".join(batch_lines)

    resp = client.models.generate_content(
        model=model_id,
        contents=[prompt, joined],
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=schema,
            generation_config=types.GenerationConfig(
                max_output_tokens=max_output_tokens
            ),
        ),
    )

    # The google-genai SDK parses JSON into Python types when schema is provided.
    # If schema is list[BaseModel], resp.parsed is List[BaseModel] instances.
    return resp.parsed