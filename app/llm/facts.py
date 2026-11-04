import re

# 15,000 / 1,50,000 (Indian grouping) / 2026 / 1.5 / 05 — a trailing "." (end of sentence) is not a decimal
_NUMBER_RE = re.compile(r"\d{1,3}(?:,\d{2,3})+(?:\.\d+)?|\d+(?:\.\d+)?")
# the clause's own number at the start of its heading ("4.", "4.2", "4)") is not a fact to preserve
_LEADING_CLAUSE_NUMBER_RE = re.compile(r"^\s*\d+(?:\.\d+)*[.)]?(?=\s)")

_UNITS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
    "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
}
_TENS = {
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
    "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
}
_SCALES = {"hundred": 100, "thousand": 1_000, "lakh": 100_000, "lakhs": 100_000, "million": 1_000_000, "crore": 10_000_000}
_ORDINALS = {
    "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6, "seventh": 7,
    "eighth": 8, "ninth": 9, "tenth": 10, "eleventh": 11, "twelfth": 12, "fifteenth": 15,
    "twentieth": 20, "thirtieth": 30,
}
_MONTHS = {
    month: index
    for index, month in enumerate(
        ["january", "february", "march", "april", "may", "june", "july",
         "august", "september", "october", "november", "december"],
        start=1,
    )
}


def _normalize(token: str) -> str:
    """"15,000" -> "15000", "05" -> "5", "1.50" -> "1.5"."""
    token = token.replace(",", "")
    if "." in token:
        whole, fraction = token.split(".", 1)
        fraction = fraction.rstrip("0")
        return f"{int(whole)}.{fraction}" if fraction else str(int(whole))
    return str(int(token))


def _numbers_in_words(text: str) -> set[str]:
    """Spelled-out numbers ("fifteen thousand", "thirty", "fifth", "March")
    so a simplification that writes a number in words still counts as keeping it.
    """
    found: set[str] = set()
    total = current = 0
    in_number = False

    def flush():
        nonlocal total, current, in_number
        if in_number:
            found.add(str(total + current))
        total = current = 0
        in_number = False

    for word in re.findall(r"[a-z]+", text.lower()):
        if word in _UNITS:
            current += _UNITS[word]
            in_number = True
        elif word in _TENS:
            current += _TENS[word]
            in_number = True
        elif word in _SCALES and in_number:
            scale = _SCALES[word]
            if scale == 100:
                current *= scale
            else:
                total += current * scale
                current = 0
        elif word == "and" and in_number:
            continue
        else:
            flush()
            if word in _ORDINALS:
                found.add(str(_ORDINALS[word]))
            elif word in _MONTHS:
                found.add(str(_MONTHS[word]))
    flush()
    return found


def missing_numbers(original: str, simplified: str) -> list[str]:
    """Numbers (amounts, dates, deadlines, percentages, section references)
    in the original that the simplification does not contain, as written in
    the original. A deterministic check that does not trust the model's own
    self_check: an empty list means every number survived, not that the
    meaning did.
    """
    original = _LEADING_CLAUSE_NUMBER_RE.sub("", original, count=1)
    kept = {_normalize(t) for t in _NUMBER_RE.findall(simplified)} | _numbers_in_words(simplified)

    missing: list[str] = []
    seen: set[str] = set()
    for token in _NUMBER_RE.findall(original):
        value = _normalize(token)
        if value not in kept and value not in seen:
            seen.add(value)
            missing.append(token)
    return missing
