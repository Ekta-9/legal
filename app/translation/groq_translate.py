import json
import re

from app.llm.simplify import CompletesPrompts
from app.translation.nllb import SUPPORTED_LANGUAGES, UnsupportedLanguageError

# Hindi/Marathi translation of the plain-English text by the same Groq model that simplifies.
# Compared on 10 plain clauses from tests/eval (2026-11-10): it kept every number, negation and
# exception in both languages; the local NLLB model lost meaning in 3 Marathi clauses, and
# Cloudflare's m2m100 in 9 of 20 (including a reversed "unless").

LANGUAGE_NAMES = {"hi": "Hindi", "mr": "Marathi"}
_DEVANAGARI_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")
_DIGITS_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")


def _numbers(text: str) -> list[str]:
    """Digit numbers only: "two" in English may rightly become "दोन" in Marathi."""
    return [n.replace(",", "").rstrip(".") for n in _DIGITS_RE.findall(text.translate(_DEVANAGARI_DIGITS))]


def missing_numbers(english: str, translated: str) -> list[str]:
    found = set(_numbers(translated))
    return [n for n in dict.fromkeys(_numbers(english)) if n not in found]


def build_prompt(text: str, target_lang: str, problem: str | None = None) -> str:
    note = f"An earlier translation had this problem: {problem}. Make sure yours does not.\n" if problem else ""
    return (
        f"Translate this plain-English explanation of a contract clause into {LANGUAGE_NAMES[target_lang]} "
        "(Devanagari script) for an ordinary reader. Translate the meaning exactly: keep every condition, "
        "exception, negation (\"must not\", \"cannot\", \"unless\") and time limit, and do not add or drop anything. "
        "Keep every number, amount, percentage and clause number as Western digits (25,000, 2%, Clause 7), "
        "but write the words around them in the target language (7th -> 7 तारीख / 7 वा). "
        "Only the names of people and companies stay in Latin letters (Priya Shah, Acme Pvt. Ltd.); "
        "translate role words such as Tenant, Owner, Licensee, Employee, Company and Supplier. "
        "Use everyday words a non-lawyer understands.\n"
        f"{note}\n"
        f"Text:\n{json.dumps(text, ensure_ascii=False)}\n\n"
        'Respond with ONLY a JSON object: {"translation": "..."}'
    )


def _parse(raw: str) -> str:
    try:
        translation = json.loads(raw)["translation"]
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        raise ValueError("translation response was not the expected JSON") from e
    if not isinstance(translation, str) or not translation.strip():
        raise ValueError("translation response was empty")
    return translation.strip()


async def translate(text: str, target_lang: str, client: CompletesPrompts) -> str:
    """One request; one retry, told what went wrong, if a number from the English
    is missing. The retry is kept unless it is missing more."""
    if target_lang not in SUPPORTED_LANGUAGES:
        raise UnsupportedLanguageError(
            f"unsupported target_lang '{target_lang}'; supported: {sorted(SUPPORTED_LANGUAGES)}"
        )
    first = _parse(await client.complete(build_prompt(text, target_lang)))
    missing = missing_numbers(text, first)
    if not missing:
        return first
    problem = f"it left out these numbers from the English: {', '.join(missing)}"
    retry = _parse(await client.complete(build_prompt(text, target_lang, problem)))
    return retry if len(missing_numbers(text, retry)) <= len(missing) else first
