"""
Shared utilities for the backend (e.g. Gemini API retry on 503).
Uses google.genai (genai.Client, client.models.generate_content).
"""

import time


def is_503_or_unavailable(exc: Exception) -> bool:
    """Return True if the exception indicates a 503 / service unavailable from the API."""
    msg = str(exc).lower()
    return "503" in msg or "unavailable" in msg or "service is currently unavailable" in msg


def generate_content_with_retry(client, model_name: str, contents: str, config=None):
    """
    Call client.models.generate_content with a simple retry on 503.
    client: genai.Client(api_key=...). On 503: wait 10 seconds, try once more.
    Returns the response (has .text).
    """
    last_err = None
    for attempt in range(2):
        try:
            kwargs = {"model": model_name, "contents": contents}
            if config is not None:
                kwargs["config"] = config
            return client.models.generate_content(**kwargs)
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
