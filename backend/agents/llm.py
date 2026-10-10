"""Shared Gemini helpers: which model to use, and free-tier retry settings."""

import time
from functools import lru_cache

from google import genai
from google.genai import types

from app import config

# After a model fails, try it last for this long instead of waiting on it again.
MODEL_COOLDOWN_SECONDS = 600

# Free tier: retry rate limits and overload with exponential backoff.
RETRY_OPTIONS = types.HttpRetryOptions(
    attempts=3, initial_delay=2.0, exp_base=2.0, max_delay=20.0,
    http_status_codes=[429, 500, 503, 504],
)

_model_failed_at: dict[str, float] = {}


def models_to_try() -> list[str]:
    """Configured models, with recently failed ones moved to the back."""
    now = time.monotonic()
    cooling = [m for m in config.GEMINI_MODELS if now - _model_failed_at.get(m, -1e9) < MODEL_COOLDOWN_SECONDS]
    return [m for m in config.GEMINI_MODELS if m not in cooling] + cooling


def mark_failed(model_name: str) -> None:
    _model_failed_at[model_name] = time.monotonic()


@lru_cache
def client() -> genai.Client:
    """google-genai client for the AI Studio key, with a timeout and retries."""
    return genai.Client(
        api_key=config.GEMINI_API_KEY,
        http_options=types.HttpOptions(timeout=60_000, retry_options=RETRY_OPTIONS),
    )
