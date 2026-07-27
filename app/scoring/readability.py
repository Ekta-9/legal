import textstat


def flesch_kincaid_grade(text: str) -> float:
    """Flesch-Kincaid grade level. textstat returns nonsense (large negative
    numbers) on empty/whitespace-only input instead of raising, so that case
    is special-cased to a flat 0.0.
    """
    if not text.strip():
        return 0.0
    return round(textstat.flesch_kincaid_grade(text), 1)


def readability_delta(original: str, simplified: str) -> dict[str, float]:
    """Before/after grade level for a clause and its simplification.
    `delta` is positive when the simplification reads at a LOWER (easier)
    grade level than the original — i.e. positive delta = improvement.
    """
    original_grade = flesch_kincaid_grade(original)
    simplified_grade = flesch_kincaid_grade(simplified)
    return {
        "original_grade": original_grade,
        "simplified_grade": simplified_grade,
        "delta": round(original_grade - simplified_grade, 1),
    }
