import asyncio
from collections.abc import Callable

from fastapi import APIRouter, HTTPException

from app.models.schemas import TranslateRequest, TranslateResponse
from app.translation.nllb import UnsupportedLanguageError

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

    try:
        # NLLB generation is CPU-bound and synchronous — run off the event loop
        translated = await asyncio.to_thread(get_translate_fn(), request.text, request.target_lang)
    except UnsupportedLanguageError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    return TranslateResponse(translated_text=translated)
