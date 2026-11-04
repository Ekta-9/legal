import re
import threading

MODEL_NAME = "facebook/nllb-200-distilled-600M"
MAX_SENTENCE_TOKENS = 400  # NLLB is trained on sentence-level pairs; translating per sentence keeps output from being cut off

# FLORES-200 codes for the languages this app offers as translation targets.
SUPPORTED_LANGUAGES = {
    "hi": "hin_Deva",  # Hindi
    "mr": "mar_Deva",  # Marathi
}

_SENTENCE_END_RE = re.compile(r"(?<=[.!?;])\s+")
# a period after these is not a sentence end ("Rs. 15,000", "Acme Pvt. Ltd.", "e.g. rent")
_ABBREVIATIONS = {
    "rs", "inr", "no", "nos", "mr", "mrs", "ms", "dr", "sr", "jr", "st", "co", "ltd", "pvt", "inc",
    "corp", "vs", "viz", "etc", "e.g", "i.e", "art", "sec", "cl", "para", "approx", "dept",
}


class UnsupportedLanguageError(ValueError):
    pass


# One lock for loading and generating: concurrent first requests used to each
# load their own ~2.4GB copy of the model (lru_cache doesn't block concurrent
# first calls), which exhausted memory and killed the server. Generation is
# CPU-bound and already multi-threaded inside torch, so serializing it costs
# little; it also protects the shared tokenizer's mutable `src_lang`.
_lock = threading.Lock()
_loaded = None


def _load():
    from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

    return AutoTokenizer.from_pretrained(MODEL_NAME), AutoModelForSeq2SeqLM.from_pretrained(MODEL_NAME)


def _get_tokenizer_and_model():
    """Caller must hold `_lock`."""
    global _loaded
    if _loaded is None:
        _loaded = _load()
    return _loaded


def _ends_with_abbreviation(fragment: str) -> bool:
    if not fragment.endswith("."):
        return False
    last_word = fragment[:-1].rsplit(None, 1)[-1].lower() if fragment[:-1].strip() else ""
    return last_word in _ABBREVIATIONS or (len(last_word) == 1 and last_word.isalpha())


def split_sentences(text: str) -> list[str]:
    sentences: list[str] = []
    for part in _SENTENCE_END_RE.split(text.strip()):
        part = part.strip()
        if not part:
            continue
        if sentences and _ends_with_abbreviation(sentences[-1]):
            sentences[-1] = f"{sentences[-1]} {part}"
        else:
            sentences.append(part)
    return sentences


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
    sentences = split_sentences(text)
    if not sentences:
        return ""

    with _lock:
        tokenizer, model = _get_tokenizer_and_model()
        tokenizer.src_lang = source_lang
        inputs = tokenizer(
            sentences, return_tensors="pt", padding=True, truncation=True, max_length=MAX_SENTENCE_TOKENS
        )
        forced_bos_token_id = tokenizer.convert_tokens_to_ids(SUPPORTED_LANGUAGES[target_lang])
        generated = model.generate(
            **inputs, forced_bos_token_id=forced_bos_token_id, max_length=MAX_SENTENCE_TOKENS
        )
        return " ".join(tokenizer.batch_decode(generated, skip_special_tokens=True))
