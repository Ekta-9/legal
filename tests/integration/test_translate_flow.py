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
