import pytest

from app.routers import translate as translate_router
from app.translation.nllb import UnsupportedLanguageError


@pytest.fixture(autouse=True)
def reset_translate_fn():
    yield
    translate_router.set_translate_fn(None)


@pytest.mark.asyncio
async def test_translate_returns_translated_text_from_injected_fn(async_client):
    def fake_translate(text: str, target_lang: str) -> str:
        return f"[{target_lang}] {text}"

    translate_router.set_translate_fn(fake_translate)

    response = await async_client.post(
        "/api/translate", json={"text": "Hello world", "target_lang": "hi"}
    )

    assert response.status_code == 200
    assert response.json() == {"translated_text": "[hi] Hello world"}


@pytest.mark.asyncio
async def test_translate_unsupported_language_returns_400(async_client):
    def fake_translate(text: str, target_lang: str) -> str:
        raise UnsupportedLanguageError(f"unsupported target_lang '{target_lang}'")

    translate_router.set_translate_fn(fake_translate)

    response = await async_client.post(
        "/api/translate", json={"text": "Hello world", "target_lang": "xx"}
    )

    assert response.status_code == 400
    assert "xx" in response.json()["detail"]


@pytest.mark.asyncio
async def test_translate_empty_text_returns_400_without_calling_translate_fn(async_client):
    calls = []
    translate_router.set_translate_fn(lambda text, target_lang: calls.append(1) or "unused")

    response = await async_client.post("/api/translate", json={"text": "   ", "target_lang": "hi"})

    assert response.status_code == 400
    assert calls == []


@pytest.mark.asyncio
async def test_translate_missing_fields_returns_422(async_client):
    response = await async_client.post("/api/translate", json={"text": "Hello"})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_translate_too_long_text_returns_413_without_calling_translate_fn(async_client, monkeypatch):
    calls = []
    translate_router.set_translate_fn(lambda text, lang: calls.append(text) or text)
    monkeypatch.setattr(translate_router, "MAX_TRANSLATE_CHARS", 10)

    response = await async_client.post("/api/translate", json={"text": "x" * 11, "target_lang": "hi"})

    assert response.status_code == 413
    assert calls == []


@pytest.mark.asyncio
async def test_translate_crash_returns_500_without_internal_details(async_client):
    def broken_translate(text: str, target_lang: str) -> str:
        raise MemoryError("CUDA out of memory at 0xdeadbeef")

    translate_router.set_translate_fn(broken_translate)
    response = await async_client.post("/api/translate", json={"text": "Hello", "target_lang": "hi"})

    assert response.status_code == 500
    assert "0xdeadbeef" not in response.text


@pytest.mark.asyncio
async def test_local_backend_without_its_packages_is_reported_unavailable(async_client, monkeypatch):
    import app.translation.backend as backend
    from app.config import settings

    monkeypatch.setattr(settings, "translation_backend", "local")
    monkeypatch.setattr(backend.importlib.util, "find_spec", lambda name: None)  # no torch installed
    assert (await async_client.get("/api/config")).json() == {"translation": False}

    response = await async_client.post("/api/translate", json={"text": "Hello", "target_lang": "hi"})
    assert response.status_code == 503


@pytest.mark.asyncio
async def test_groq_backend_needs_only_the_groq_key(async_client, monkeypatch):
    import app.translation.backend as backend
    from app.config import settings

    monkeypatch.setattr(settings, "translation_backend", "groq")
    monkeypatch.setattr(backend.importlib.util, "find_spec", lambda name: None)  # as on Render: no torch
    monkeypatch.setattr(settings, "groq_api_key", "test-key")
    assert (await async_client.get("/api/config")).json() == {"translation": True}
    monkeypatch.setattr(settings, "groq_api_key", "")
    assert (await async_client.get("/api/config")).json() == {"translation": False}


@pytest.mark.asyncio
async def test_translation_can_be_switched_off(async_client, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "groq_api_key", "test-key")
    monkeypatch.setattr(settings, "translation_enabled", False)
    assert (await async_client.get("/api/config")).json() == {"translation": False}


@pytest.mark.asyncio
async def test_groq_translation_through_the_endpoint(async_client, monkeypatch):
    import json

    from app.config import settings
    from app.jobs import pipeline

    class FakeGroq:
        async def complete(self, prompt):
            return json.dumps({"translation": "किरायेदार को हर महीने Rs. 22,000 देने होंगे।"})

    monkeypatch.setattr(settings, "translation_backend", "groq")
    pipeline.set_client(FakeGroq())
    try:
        response = await async_client.post("/api/translate", json={"text": "The Tenant must pay Rs. 22,000 every month.", "target_lang": "hi"})
    finally:
        pipeline.set_client(None)
    assert response.status_code == 200
    assert response.json() == {"translated_text": "किरायेदार को हर महीने Rs. 22,000 देने होंगे।"}


@pytest.mark.asyncio
async def test_daily_limit_during_translation_says_the_server_is_busy(async_client):
    import httpx
    from groq import RateLimitError

    async def limited(text, target_lang):
        response = httpx.Response(429, request=httpx.Request("POST", "https://api.groq.com"))
        raise RateLimitError("tokens per day (TPD) ... Please try again in 4m10s.", response=response, body=None)

    translate_router.set_translate_fn(limited)
    response = await async_client.post("/api/translate", json={"text": "Hello", "target_lang": "hi"})
    assert response.status_code == 503
    assert response.json()["detail"] == "The server is busy. Please try again in about 5 minutes."
