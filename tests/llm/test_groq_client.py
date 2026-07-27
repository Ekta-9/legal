import asyncio

import httpx
import pytest
from groq import RateLimitError

from app.llm.groq_client import GroqClient, batch_items


def _rate_limit_error() -> RateLimitError:
    request = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
    response = httpx.Response(429, request=request)
    return RateLimitError("rate limited", response=response, body=None)


def test_batch_items_splits_into_expected_group_sizes():
    assert batch_items([1, 2, 3, 4, 5, 6, 7], 3) == [[1, 2, 3], [4, 5, 6], [7]]
    assert batch_items([], 3) == []
    assert batch_items([1, 2], 5) == [[1, 2]]


@pytest.mark.asyncio
async def test_semaphore_caps_concurrent_calls():
    concurrency = 2
    in_flight = 0
    max_in_flight = 0
    lock = asyncio.Lock()

    async def call_fn(prompt: str) -> str:
        nonlocal in_flight, max_in_flight
        async with lock:
            in_flight += 1
            max_in_flight = max(max_in_flight, in_flight)
        await asyncio.sleep(0.01)
        async with lock:
            in_flight -= 1
        return "{}"

    client = GroqClient(call_fn=call_fn, concurrency=concurrency)
    await asyncio.gather(*(client.complete(f"prompt {i}") for i in range(6)))

    assert max_in_flight <= concurrency


@pytest.mark.asyncio
async def test_429_triggers_backoff_then_retry_succeeds():
    attempts = 0
    sleeps: list[float] = []

    async def call_fn(prompt: str) -> str:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise _rate_limit_error()
        return "ok"

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    client = GroqClient(call_fn=call_fn, max_retries=5, backoff_base=1.0, sleep_fn=fake_sleep)
    result = await client.complete("prompt")

    assert result == "ok"
    assert attempts == 3
    assert sleeps == [1.0, 2.0]  # exponential: base * 2^0, base * 2^1


@pytest.mark.asyncio
async def test_429_exhausts_retries_and_raises():
    async def call_fn(prompt: str) -> str:
        raise _rate_limit_error()

    async def fake_sleep(delay: float) -> None:
        return None

    client = GroqClient(call_fn=call_fn, max_retries=2, backoff_base=0.01, sleep_fn=fake_sleep)

    with pytest.raises(RateLimitError):
        await client.complete("prompt")
