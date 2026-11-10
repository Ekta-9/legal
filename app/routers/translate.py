import asyncio
import inspect
import logging
from collections.abc import Awaitable, Callable

import groq
from fastapi import APIRouter, HTTPException

from app.config import settings
from app.constants import MAX_TRANSLATE_CHARS
from app.models.schemas import TranslateRequest, TranslateResponse
from app.translation.backend import translation_available
from app.translation.nllb import UnsupportedLanguageError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/translate", tags=["translation"])

# (text, target_lang) -> translated text; the Groq translator is async, the local NLLB one is not
TranslateFn = Callable[[str, str], str | Awaitable[str]]

_translate_fn: TranslateFn | None = None


def get_translate_fn() -> TranslateFn:
    global _translate_fn
    if _translate_fn is None:
        if settings.translation_backend == "local":
            from app.translation.nllb import translate  # deferred: avoid loading the ~2.4GB model unless used

            _translate_fn = translate
        else:
            from app.jobs.pipeline import get_client
            from app.translation.groq_translate import translate as groq_translate

            async def translate(text: str, target_lang: str) -> str:
                # the same client as simplification: one concurrency limit and retry policy for the key
                return await groq_translate(text, target_lang, get_client())

            _translate_fn = translate
    return _translate_fn


def set_translate_fn(fn: TranslateFn | None) -> None:
    """Test/DI hook — swap in a fake translator, or pass None to reset to
    the lazily-constructed real one on next use.
    """
    global _translate_fn
    _translate_fn = fn


@router.post("", response_model=TranslateResponse)
async def translate_text(request: TranslateRequest) -> TranslateResponse:
    if not request.text.strip():
        raise HTTPException(status_code=400, detail="text is empty")
    if len(request.text) > MAX_TRANSLATE_CHARS:
        raise HTTPException(status_code=413, detail=f"text is too long (limit {MAX_TRANSLATE_CHARS:,} characters)")
    if _translate_fn is None and not translation_available():
        raise HTTPException(status_code=503, detail="translation is not available on this server")

    translate = get_translate_fn()
    try:
        if inspect.iscoroutinefunction(translate):
            translated = await translate(request.text, request.target_lang)
        else:
            # local NLLB generation is CPU-bound and synchronous — run off the event loop
            translated = await asyncio.to_thread(translate, request.text, request.target_lang)
    except UnsupportedLanguageError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except groq.RateLimitError as e:
        from app.jobs.pipeline import user_message

        raise HTTPException(status_code=503, detail=user_message(e)) from e
    except Exception as e:
        logger.exception("Translation to %s failed", request.target_lang)
        raise HTTPException(status_code=500, detail="translation failed on the server") from e

    return TranslateResponse(translated_text=translated)
