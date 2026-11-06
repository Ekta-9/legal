import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import TypeVar

from groq import APIConnectionError, AsyncGroq, BadRequestError, InternalServerError, RateLimitError

from app.config import settings
from app.constants import (
    GROQ_BACKOFF_BASE_SECONDS,
    GROQ_MAX_BACKOFF_SECONDS,
    GROQ_MAX_COMPLETION_TOKENS,
    GROQ_MAX_RATE_LIMIT_RETRIES,
    GROQ_MAX_RETRIES,
    GROQ_TEMPERATURE,
    GROQ_TIMEOUT_SECONDS,
)

logger = logging.getLogger(__name__)

T = TypeVar("T")

# APIConnectionError includes APITimeoutError
RETRYABLE_ERRORS = (RateLimitError, APIConnectionError, InternalServerError, BadRequestError)


def _is_retryable(error: Exception) -> bool:
    """A 400 is normally our mistake and retrying won't help — except Groq's
    json_validate_failed, which means the model produced invalid JSON this time."""
    if isinstance(error, BadRequestError):
        body = error.body if isinstance(error.body, dict) else {}
        return (body.get("error", body) or {}).get("code") == "json_validate_failed"
    return True

CallFn = Callable[[str], Awaitable[str]]


def batch_items(items: list[T], size: int) -> list[list[T]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def _default_call_fn(api_key: str | None, model: str | None) -> CallFn:
    # max_retries=0: GroqClient.complete owns retries, so they don't multiply with the SDK's
    client = AsyncGroq(
        api_key=api_key or settings.groq_api_key,
        max_retries=0,
        timeout=GROQ_TIMEOUT_SECONDS,
    )
    resolved_model = model or settings.groq_model

    async def call(prompt: str) -> str:
        response = await client.chat.completions.create(
            model=resolved_model,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=GROQ_TEMPERATURE,
            max_completion_tokens=GROQ_MAX_COMPLETION_TOKENS,
        )
        choice = response.choices[0]
        if choice.finish_reason == "length":
            # the JSON is cut off; parse_batch_response reports its clauses as dropped and they are re-requested
            logger.warning("Groq response hit the %d-token limit and was truncated", GROQ_MAX_COMPLETION_TOKENS)
        return choice.message.content or ""

    return call


def _retry_after(error: Exception) -> float | None:
    response = getattr(error, "response", None)
    if response is None:
        return None
    try:
        return float(response.headers.get("retry-after"))
    except (TypeError, ValueError):
        return None


class GroqClient:
    """Async wrapper around the Groq SDK: concurrency ceiling + exponential
    backoff on rate limits and transient failures. The underlying call is
    injectable (`call_fn`) so tests never need a real API key or network access.

    Rate limits get their own, larger retry budget: a 429 means "wait", not
    "failed", and on the free tier a few concurrent batches hit the
    tokens-per-minute limit routinely.
    """

    def __init__(
        self,
        call_fn: CallFn | None = None,
        api_key: str | None = None,
        model: str | None = None,
        concurrency: int | None = None,
        max_retries: int = GROQ_MAX_RETRIES,
        max_rate_limit_retries: int = GROQ_MAX_RATE_LIMIT_RETRIES,
        backoff_base: float = GROQ_BACKOFF_BASE_SECONDS,
        sleep_fn: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ):
        self._call_fn = call_fn or _default_call_fn(api_key, model)
        self._semaphore = asyncio.Semaphore(concurrency or settings.groq_concurrency)
        self._max_retries = max_retries
        self._max_rate_limit_retries = max_rate_limit_retries
        self._backoff_base = backoff_base
        self._sleep_fn = sleep_fn

    async def complete(self, prompt: str) -> str:
        async with self._semaphore:
            failures = rate_limits = 0
            while True:
                try:
                    return await self._call_fn(prompt)
                except RETRYABLE_ERRORS as e:
                    if not _is_retryable(e):
                        raise
                    if isinstance(e, RateLimitError):
                        rate_limits += 1
                        attempt, limit = rate_limits, self._max_rate_limit_retries
                    else:
                        failures += 1
                        attempt, limit = failures, self._max_retries
                    if attempt > limit:
                        raise
                    delay = self._backoff_base * (2 ** (attempt - 1))
                    if isinstance(e, RateLimitError):
                        delay = max(delay, _retry_after(e) or 0.0)
                    delay = min(delay, GROQ_MAX_BACKOFF_SECONDS)
                    logger.warning(
                        "Groq call failed (%s), retry %d/%d in %.1fs",
                        type(e).__name__, attempt, limit, delay,
                    )
                    await self._sleep_fn(delay)
