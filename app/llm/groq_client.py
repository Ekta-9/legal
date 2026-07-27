import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar

from groq import AsyncGroq, RateLimitError

from app.config import settings
from app.constants import (
    GROQ_BACKOFF_BASE_SECONDS,
    GROQ_CONCURRENCY,
    GROQ_MAX_RETRIES,
)

T = TypeVar("T")

CallFn = Callable[[str], Awaitable[str]]


def batch_items(items: list[T], size: int) -> list[list[T]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def _default_call_fn(api_key: str | None, model: str | None) -> CallFn:
    client = AsyncGroq(api_key=api_key or settings.groq_api_key)
    resolved_model = model or settings.groq_model

    async def call(prompt: str) -> str:
        response = await client.chat.completions.create(
            model=resolved_model,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
        )
        return response.choices[0].message.content or ""

    return call


class GroqClient:
    """Async wrapper around the Groq SDK: concurrency ceiling + exponential
    backoff on 429. The underlying call is injectable (`call_fn`) so tests
    never need a real API key or network access.
    """

    def __init__(
        self,
        call_fn: CallFn | None = None,
        api_key: str | None = None,
        model: str | None = None,
        concurrency: int = GROQ_CONCURRENCY,
        max_retries: int = GROQ_MAX_RETRIES,
        backoff_base: float = GROQ_BACKOFF_BASE_SECONDS,
        sleep_fn: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ):
        self._call_fn = call_fn or _default_call_fn(api_key, model)
        self._semaphore = asyncio.Semaphore(concurrency)
        self._max_retries = max_retries
        self._backoff_base = backoff_base
        self._sleep_fn = sleep_fn

    async def complete(self, prompt: str) -> str:
        async with self._semaphore:
            attempt = 0
            while True:
                try:
                    return await self._call_fn(prompt)
                except RateLimitError:
                    attempt += 1
                    if attempt > self._max_retries:
                        raise
                    delay = self._backoff_base * (2 ** (attempt - 1))
                    await self._sleep_fn(delay)
