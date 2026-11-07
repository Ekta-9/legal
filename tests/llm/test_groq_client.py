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

    client = GroqClient(call_fn=call_fn, max_rate_limit_retries=2, backoff_base=0.01, sleep_fn=fake_sleep)

    with pytest.raises(RateLimitError):
        await client.complete("prompt")


def _error_with_status(error_cls, status: int, headers: dict | None = None):
    request = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
    response = httpx.Response(status, request=request, headers=headers or {})
    return error_cls("error", response=response, body=None)


@pytest.mark.asyncio
async def test_connection_errors_and_5xx_are_retried():
    from groq import APIConnectionError, InternalServerError

    request = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
    errors = [APIConnectionError(request=request), _error_with_status(InternalServerError, 503)]

    async def call_fn(prompt: str) -> str:
        if errors:
            raise errors.pop(0)
        return "ok"

    async def fake_sleep(delay: float) -> None:
        return None

    client = GroqClient(call_fn=call_fn, sleep_fn=fake_sleep)
    assert await client.complete("prompt") == "ok"


@pytest.mark.asyncio
async def test_auth_errors_are_not_retried():
    from groq import AuthenticationError

    attempts = 0

    async def call_fn(prompt: str) -> str:
        nonlocal attempts
        attempts += 1
        raise _error_with_status(AuthenticationError, 401)

    client = GroqClient(call_fn=call_fn, sleep_fn=lambda delay: asyncio.sleep(0))
    with pytest.raises(AuthenticationError):
        await client.complete("prompt")
    assert attempts == 1


@pytest.mark.asyncio
async def test_rate_limit_waits_for_retry_after_but_never_longer_than_the_cap():
    from app.constants import GROQ_MAX_BACKOFF_SECONDS

    errors = [
        _error_with_status(RateLimitError, 429, {"retry-after": "7"}),
        _error_with_status(RateLimitError, 429, {"retry-after": "45"}),
    ]
    sleeps: list[float] = []

    async def call_fn(prompt: str) -> str:
        if errors:
            raise errors.pop(0)
        return "ok"

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    client = GroqClient(call_fn=call_fn, backoff_base=1.0, sleep_fn=fake_sleep)
    await client.complete("prompt")
    assert sleeps == [7.0, GROQ_MAX_BACKOFF_SECONDS]


def test_sdk_retries_are_disabled_so_they_do_not_multiply_with_ours():
    from app.llm import groq_client

    captured = {}

    class FakeAsyncGroq:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    original = groq_client.AsyncGroq
    groq_client.AsyncGroq = FakeAsyncGroq
    try:
        groq_client._default_call_fn("test-key", "test-model")
    finally:
        groq_client.AsyncGroq = original
    assert captured["max_retries"] == 0


@pytest.mark.asyncio
async def test_rate_limits_have_a_larger_budget_than_other_failures():
    from app.constants import GROQ_MAX_RATE_LIMIT_RETRIES, GROQ_MAX_RETRIES

    remaining = GROQ_MAX_RETRIES + 2  # more 429s than the ordinary retry budget allows

    async def call_fn(prompt: str) -> str:
        nonlocal remaining
        if remaining:
            remaining -= 1
            raise _rate_limit_error()
        return "ok"

    async def fake_sleep(delay: float) -> None:
        return None

    assert GROQ_MAX_RATE_LIMIT_RETRIES > GROQ_MAX_RETRIES + 2
    client = GroqClient(call_fn=call_fn, sleep_fn=fake_sleep)
    assert await client.complete("prompt") == "ok"


@pytest.mark.asyncio
async def test_invalid_json_from_the_model_is_retried_but_other_bad_requests_are_not():
    from groq import BadRequestError

    def bad_request(code):
        return _error_with_status(BadRequestError, 400) if code is None else BadRequestError(
            "error",
            response=httpx.Response(400, request=httpx.Request("POST", "https://api.groq.com")),
            body={"error": {"code": code, "message": "Failed to validate JSON"}},
        )

    async def no_sleep(delay: float) -> None:
        return None

    errors = [bad_request("json_validate_failed")]

    async def flaky(prompt: str) -> str:
        if errors:
            raise errors.pop(0)
        return "ok"

    assert await GroqClient(call_fn=flaky, sleep_fn=no_sleep).complete("prompt") == "ok"

    attempts = 0

    async def always_bad(prompt: str) -> str:
        nonlocal attempts
        attempts += 1
        raise bad_request("model_not_found")

    with pytest.raises(BadRequestError):
        await GroqClient(call_fn=always_bad, sleep_fn=no_sleep).complete("prompt")
    assert attempts == 1


class _FakeCompletions:
    """Stands in for AsyncGroq().chat.completions: 413 above `limit` output tokens."""

    def __init__(self, limit: int):
        self.limit = limit
        self.max_tokens_seen = []

    async def create(self, **kwargs):
        from types import SimpleNamespace

        from groq import APIStatusError

        self.max_tokens_seen.append(kwargs["max_completion_tokens"])
        if kwargs["max_completion_tokens"] > self.limit:
            raise _error_with_status(APIStatusError, 413)
        message = SimpleNamespace(content='{"results": []}')
        return SimpleNamespace(choices=[SimpleNamespace(finish_reason="stop", message=message)])


@pytest.mark.asyncio
async def test_request_too_large_is_retried_once_with_a_smaller_output_allowance(monkeypatch):
    from types import SimpleNamespace

    import app.llm.groq_client as groq_client
    from app.constants import GROQ_MAX_COMPLETION_TOKENS, GROQ_REDUCED_COMPLETION_TOKENS

    completions = _FakeCompletions(limit=GROQ_REDUCED_COMPLETION_TOKENS)
    monkeypatch.setattr(groq_client, "AsyncGroq", lambda **_: SimpleNamespace(chat=SimpleNamespace(completions=completions)))
    call = groq_client._default_call_fn("key", "model")

    assert await call("prompt") == '{"results": []}'
    assert completions.max_tokens_seen == [GROQ_MAX_COMPLETION_TOKENS, GROQ_REDUCED_COMPLETION_TOKENS]

    completions.limit = 0  # still too large: raised, so the caller can halve the batch
    with pytest.raises(Exception) as raised:
        await call("prompt")
    assert raised.value.status_code == 413


DAILY_LIMIT_MESSAGE = (
    "Rate limit reached for model `openai/gpt-oss-20b` on tokens per day (TPD): Limit 200000, "
    "Used 199726, Requested 2081. Please try again in 13m0.624s."
)


@pytest.mark.asyncio
async def test_daily_limit_is_raised_at_once_not_retried_for_minutes():
    attempts = 0

    async def call_fn(prompt: str) -> str:
        nonlocal attempts
        attempts += 1
        raise RateLimitError(DAILY_LIMIT_MESSAGE, response=_error_with_status(RateLimitError, 429).response, body=None)

    async def fake_sleep(delay: float) -> None:
        raise AssertionError("must not wait on a daily limit")

    client = GroqClient(call_fn=call_fn, sleep_fn=fake_sleep)
    with pytest.raises(RateLimitError):
        await client.complete("prompt")
    assert attempts == 1


def test_a_long_retry_after_counts_as_the_daily_limit():
    from app.llm.groq_client import is_daily_limit

    assert is_daily_limit(_error_with_status(RateLimitError, 429, {"retry-after": "780"}))
    assert not is_daily_limit(_error_with_status(RateLimitError, 429, {"retry-after": "7"}))


def test_daily_limit_message_says_how_long_to_wait():
    from app.jobs.pipeline import user_message

    error = RateLimitError(DAILY_LIMIT_MESSAGE, response=_error_with_status(RateLimitError, 429).response, body=None)
    assert user_message(error) == "The free Groq quota for today is used up for this model. Try again in about 14 minutes."
