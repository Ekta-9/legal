from functools import lru_cache

MODEL_NAME = "facebook/nllb-200-distilled-600M"

# FLORES-200 codes for the languages this app offers as translation targets.
SUPPORTED_LANGUAGES = {
    "hi": "hin_Deva",  # Hindi
    "mr": "mar_Deva",  # Marathi
}


class UnsupportedLanguageError(ValueError):
    pass


@lru_cache(maxsize=1)
def _get_tokenizer():
    from transformers import AutoTokenizer

    return AutoTokenizer.from_pretrained(MODEL_NAME)


@lru_cache(maxsize=1)
def _get_model():
    from transformers import AutoModelForSeq2SeqLM

    return AutoModelForSeq2SeqLM.from_pretrained(MODEL_NAME)


def translate(text: str, target_lang: str, source_lang: str = "eng_Latn") -> str:
    """EXPERIMENTAL: local NLLB-200-distilled-600M translation. Legal
    translation quality has not been QA'd by a fluent reader — PLANNING.md
    deliberately keeps this off the critical path and without an automated
    quality gate. Treat output as a rough aid, not an authoritative
    translation.
    """
    if target_lang not in SUPPORTED_LANGUAGES:
        raise UnsupportedLanguageError(
            f"unsupported target_lang '{target_lang}'; supported: {sorted(SUPPORTED_LANGUAGES)}"
        )
    if not text.strip():
        return ""

    tokenizer = _get_tokenizer()
    tokenizer.src_lang = source_lang
    model = _get_model()

    inputs = tokenizer(text, return_tensors="pt")
    forced_bos_token_id = tokenizer.convert_tokens_to_ids(SUPPORTED_LANGUAGES[target_lang])
    generated = model.generate(**inputs, forced_bos_token_id=forced_bos_token_id, max_length=512)
    return tokenizer.batch_decode(generated, skip_special_tokens=True)[0]
