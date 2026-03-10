"""
Shared utilities for the backend (e.g. Gemini API retry on 503).
"""

import time


def is_503_or_unavailable(exc: Exception) -> bool:
    """Return True if the exception indicates a 503 / service unavailable from the API."""
    msg = str(exc).lower()
    return "503" in msg or "unavailable" in msg or "service is currently unavailable" in msg


def generate_content_with_retry(client, model: str, contents: str, **kwargs):
    """
    Call client.models.generate_content with a simple retry on 503.
    On 503: wait 10 seconds, try once more. If it fails again, log and re-raise.
    Uses time.sleep so it works in sync context (analyzer and scraper bouncer).
    """
    last_err = None
    for attempt in range(2):
        try:
            return client.models.generate_content(model=model, contents=contents, **kwargs)
        except Exception as e:
            last_err = e
            if is_503_or_unavailable(e) and attempt == 0:
                print(f"⚠️ Gemini 503 / unavailable, waiting 10s before retry...")
                time.sleep(10)
                continue
            raise
    if last_err is not None:
        print(f"⚠️ Gemini request failed after retry: {last_err}")
        raise last_err
