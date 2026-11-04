import asyncio
import logging
from collections.abc import Callable

from fastapi import APIRouter, HTTPException

from app.constants import MAX_TRANSLATE_CHARS
from app.models.schemas import TranslateRequest, TranslateResponse
from app.translation.nllb import UnsupportedLanguageError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/translate", tags=["translation"])

TranslateFn = Callable[[str, str], str]

_translate_fn: TranslateFn | None = None


def get_translate_fn() -> TranslateFn:
    global _translate_fn
    if _translate_fn is None:
        from app.translation.nllb import translate  # deferred: avoid loading the ~2.4GB model unless used

        _translate_fn = translate
    return _translate_fn


def set_translate_fn(fn: TranslateFn | None) -> None:
    """Test/DI hook — swap in a fake translator, or pass None to reset to
    the lazily-constructed real NLLB wrapper on next use.
    """
    global _translate_fn
    _translate_fn = fn


@router.post("", response_model=TranslateResponse)
async def translate_text(request: TranslateRequest) -> TranslateResponse:
    if not request.text.strip():
        raise HTTPException(status_code=400, detail="text is empty")
    if len(request.text) > MAX_TRANSLATE_CHARS:
        raise HTTPException(status_code=413, detail=f"text is too long (limit {MAX_TRANSLATE_CHARS:,} characters)")

    try:
        # NLLB generation is CPU-bound and synchronous — run off the event loop
        translated = await asyncio.to_thread(get_translate_fn(), request.text, request.target_lang)
    except UnsupportedLanguageError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        logger.exception("Translation to %s failed", request.target_lang)
        raise HTTPException(status_code=500, detail="translation failed on the server") from e

    return TranslateResponse(translated_text=translated)
