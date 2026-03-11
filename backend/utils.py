"""
Shared utilities for the backend (e.g. Gemini API retry on 503).
Uses google.generativeai (genai.configure, GenerativeModel).
"""

import time
import google.generativeai as genai


def is_503_or_unavailable(exc: Exception) -> bool:
    """Return True if the exception indicates a 503 / service unavailable from the API."""
    msg = str(exc).lower()
    return "503" in msg or "unavailable" in msg or "service is currently unavailable" in msg


def generate_content_with_retry(model_name: str, contents: str, api_key: str, generation_config=None):
    """
    Call genai.GenerativeModel(model_name).generate_content with a simple retry on 503.
    Uses google.generativeai: genai.configure(api_key), then GenerativeModel(...).generate_content(...).
    On 503: wait 10 seconds, try once more. Returns the response (has .text).
    """
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(model_name)
    last_err = None
    for attempt in range(2):
        try:
            kwargs = {}
            if generation_config is not None:
                kwargs["generation_config"] = generation_config
            return model.generate_content(contents, **kwargs)
        except Exception as e:
            last_err = e
            if is_503_or_unavailable(e) and attempt == 0:
                print("⚠️ Gemini 503 / unavailable, waiting 10s before retry...")
                time.sleep(10)
                continue
            raise
    if last_err is not None:
        print(f"⚠️ Gemini request failed after retry: {last_err}")
        raise last_err
