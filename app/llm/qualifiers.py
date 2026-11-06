import re
from dataclasses import dataclass

# Words that decide what a clause means but are easy to lose in a rewrite. Like
# app/llm/facts.py for numbers, a deterministic check that does not trust the
# model: if the original has one, the plain version must say it some other way.
# Exceptions ("unless", "except") are not checked: a faithful rewrite often turns
# "... except that the Supplier may assign to an Affiliate" into a separate
# sentence with no exception word, and the check flagged only such correct answers.


@dataclass(frozen=True)
class _Qualifier:
    name: str  # shown to the reader: "Missing from plain version: the override ("notwithstanding")"
    original: re.Pattern
    kept: re.Pattern
    contradicts: re.Pattern | None = None  # wording in the plain version that reverses it


def _words(*alternatives: str) -> re.Pattern:
    return re.compile(r"\b(?:" + "|".join(alternatives) + r")\b", re.IGNORECASE)


_QUALIFIERS = [
    _Qualifier(
        "the override (\"notwithstanding\")",
        _words(r"notwithstanding\s+any(?:thing)?", r"notwithstanding\s+(?:any\s+)?other\s+provisions?", r"regardless\s+of\s+any(?:thing)?"),
        _words(
            "notwithstanding", "regardless", "despite", r"even\s+if", r"even\s+though", r"overrid\w*", r"no\s+matter",
            r"whatever\s+else", r"anything\s+else", r"any\s+other\s+(?:term|provision|clause|part)s?", r"takes?\s+(?:precedence|priority)",
        ),
        # "Except as otherwise stated" makes the rest of the contract override this clause: the opposite
        _words(r"(?:except|unless)\s+(?:as\s+)?otherwise\s+(?:stated|provided|agreed|specified|set\s+out)"),
    ),
    _Qualifier(
        # without it, a breach that cannot be fixed still seems to get the cure period
        "the condition (\"if capable of remedy\")",
        _words(r"capable\s+of\s+(?:being\s+)?(?:remed\w*|cured)", "remediable", "curable"),
        _words(
            "capable", r"can\s+be\s+(?:fixed|remedied|cured|corrected)", r"can(?:not|'t)\s+be", r"could\s+be",
            r"if\s+(?:it\s+is\s+|that\s+is\s+)?possible", r"(?:ir)?remediable", r"(?:in)?curable", "fixable", "unfixable",
        ),
    ),
    _Qualifier(
        "the prohibition (\"shall not\")",
        _words(r"shall\s+not", r"must\s+not", r"may\s+not", "cannot", r"will\s+not", "neither", r"no\s+party"),
        _words(r"not", "no", "never", "neither", "nor", r"\w+n't", "cannot", "only", r"prohibit\w*", r"forbid\w*", "without"),
    ),
    _Qualifier(
        "the exclusivity (\"sole\" / \"exclusive\")",
        _words(r"sole\s+and\s+exclusive", r"sole\s+remedy", r"exclusive\s+remedy", r"exclusive\s+jurisdiction"),
        _words("only", "sole", r"exclusive\w*", r"nothing\s+else", r"no\s+other"),
    ),
]


def lost_qualifiers(original: str, simplified: str) -> list[str]:
    """Qualifiers the original has that the plain version lost or reversed.
    An empty list means none of these few markers went missing, not that the
    meaning survived."""
    lost = []
    for qualifier in _QUALIFIERS:
        if not qualifier.original.search(original):
            continue
        reversed_ = qualifier.contradicts is not None and qualifier.contradicts.search(simplified)
        if reversed_ or not qualifier.kept.search(simplified):
            lost.append(qualifier.name)
    return lost
