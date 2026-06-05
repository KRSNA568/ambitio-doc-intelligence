"""
llm.py
------
Single point of contact for the LLM provider (Google Gemini).

processor.py, generator.py, and learner.py all need text generation. Routing
every call through this one module means there is exactly one place that knows
which provider/model/SDK is in use — swapping providers or models is a one-file
change, and each caller stays provider-agnostic.

Uses the unified `google-genai` SDK:
    pip install google-genai
    export GEMINI_API_KEY=...
"""

from __future__ import annotations

import json
import os
import re
import time
from typing import Any

# Override with GEMINI_MODEL if you want pro-tier quality, e.g. "gemini-2.5-pro".
DEFAULT_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")

# Transient-error retry policy (mainly for 429 rate limits on the free tier).
MAX_RETRIES = int(os.environ.get("LLM_MAX_RETRIES", "3"))
MAX_BACKOFF_SECONDS = float(os.environ.get("LLM_MAX_BACKOFF", "30"))


def api_key_set() -> bool:
    """Cheap probe used by /health."""
    return bool(os.environ.get("GEMINI_API_KEY"))


def _client():
    """Lazily build a Gemini client so the module imports without a key."""
    from google import genai

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "GEMINI_API_KEY is not set. Export it before calling the LLM."
        )
    return genai.Client(api_key=api_key)


def generate_text(
    system: str,
    user: str,
    max_tokens: int = 1024,
    temperature: float = 0.2,
) -> str:
    """
    Run a single-turn generation and return the model's text.

    `system` becomes Gemini's system_instruction; `user` is the prompt content.
    Raises on transport/SDK errors — callers wrap this in try/except and turn
    failures into meaningful messages.
    """
    from google.genai import types

    client = _client()
    config = types.GenerateContentConfig(
        system_instruction=system,
        max_output_tokens=max_tokens,
        temperature=temperature,
        # Gemini 2.5 enables "thinking" by default, and those tokens are
        # drawn from max_output_tokens. For our structured-JSON and drafting
        # tasks that occasionally let thinking consume the whole budget and
        # truncate the real output, so we disable it for deterministic,
        # complete responses. (Supported on gemini-2.5-flash.)
        thinking_config=types.ThinkingConfig(thinking_budget=0),
    )

    last_exc: Exception | None = None
    for attempt in range(MAX_RETRIES):
        try:
            response = client.models.generate_content(
                model=DEFAULT_MODEL, contents=user, config=config
            )
            return (response.text or "").strip()
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            # Only retry transient rate-limit / overload errors.
            if not _is_retryable(exc) or attempt == MAX_RETRIES - 1:
                raise
            delay = min(_retry_delay(exc, attempt), MAX_BACKOFF_SECONDS)
            time.sleep(delay)
    # Unreachable, but keeps type checkers happy.
    raise last_exc  # type: ignore[misc]


def _is_retryable(exc: Exception) -> bool:
    """True for 429 (rate limit) and 503 (overloaded) style errors."""
    text = str(exc)
    return any(code in text for code in ("429", "RESOURCE_EXHAUSTED", "503", "UNAVAILABLE"))


def _retry_delay(exc: Exception, attempt: int) -> float:
    """
    Honor the server's suggested retryDelay if present, else exponential
    backoff (1s, 2s, 4s, ...).
    """
    match = re.search(r"retryDelay['\":\s]+(\d+(?:\.\d+)?)s", str(exc))
    if match:
        return float(match.group(1))
    return float(2 ** attempt)


def extract_json(text: str) -> Any:
    """
    Parse the first JSON value out of an LLM response.

    LLMs (Gemini in particular) often wrap JSON in a ```json fence and/or append
    a trailing sentence of explanation. We therefore: strip any code fence, jump
    to the first '{' or '[', and use raw_decode so trailing prose after a valid
    JSON value is ignored rather than raising "Extra data".

    Raises ValueError if no JSON value can be found.
    """
    s = text.strip()

    # Drop a leading ```/```json fence line and any trailing fence.
    if s.startswith("```"):
        s = s.split("\n", 1)[1] if "\n" in s else s[3:]
        if s.rstrip().endswith("```"):
            s = s.rstrip()[:-3]
    s = s.strip()

    # Locate the first JSON container.
    candidates = [i for i in (s.find("{"), s.find("[")) if i != -1]
    if not candidates:
        raise ValueError("No JSON object or array found in LLM response.")

    obj, _ = json.JSONDecoder().raw_decode(s[min(candidates):])
    return obj
