"""Shared Gemini client with strict, bounded failure handling."""

from __future__ import annotations

import json
import logging
import os
import time
from functools import lru_cache
from typing import Any, TypeVar

logger = logging.getLogger(__name__)
DEFAULT_GEMINI_MODEL = os.getenv("GENFORGE_GEMINI_MODEL", "gemini-2.5-flash")
T = TypeVar("T")


@lru_cache(maxsize=1)
def get_gemini_client() -> Any:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not configured.")
    try:
        from google import genai
        from google.genai import types
    except ImportError as exc:
        raise RuntimeError("The google-genai package is not installed.") from exc
    return genai.Client(api_key=api_key, http_options=types.HttpOptions(timeout=120000))


def generate_json(prompt: str, response_schema: Any = None, contents: Any = None, retries: int = 2) -> dict:
    """Generate and validate JSON, retrying transient API failures without fabricating data."""
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("AI prompt must be non-empty.")
    try:
        from google.genai import types  # guarded: raises RuntimeError if not installed
    except ImportError as exc:
        raise RuntimeError("The google-genai package is not installed.") from exc
    config_kwargs = {"response_mime_type": "application/json"}
    if response_schema is not None:
        config_kwargs["response_schema"] = response_schema
    config = types.GenerateContentConfig(**config_kwargs)
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            response = get_gemini_client().models.generate_content(
                model=DEFAULT_GEMINI_MODEL, contents=contents or prompt, config=config
            )
            text = getattr(response, "text", "")
            if not text:
                raise RuntimeError("Gemini returned an empty response.")
            value = json.loads(text)
            if not isinstance(value, dict):
                raise ValueError("Gemini response was not a JSON object.")
            return value
        except Exception as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(2 ** attempt)
    raise RuntimeError(f"Gemini request failed after {retries + 1} attempts: {last_error}") from last_error
