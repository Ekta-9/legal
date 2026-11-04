import re

from app.models.schemas import Clause

PREAMBLE_HEADING = "Preamble"

# "1. Rent" / "2) Term" / "1.1. Fees" / "1.1 Fees" (sub-numbers may omit the trailing dot).
# Numbers are capped at 3 digits so a wrapped line starting "2025. The term..." never matches.
_NUMBERED_RE = re.compile(
    r"^\s*(?P<num>\d{1,3}(?:\.\d{1,3})*)(?:[.)](?:\s+(?P<rest>\S.*))?|\s+(?P<rest_nodot>\S.*))$"
)
_ARTICLE_RE = re.compile(
    r"^\s*(?:SECTION|ARTICLE|CLAUSE)\s+(?P<num>[IVXLC]+|\d{1,3}(?:\.\d{1,3})*)\b(?P<rest>.*)$",
    re.IGNORECASE,
)
_SENTENCE_END = (".", "!", "?", ";", ":", '"', "”", ")")
MAX_NUMBER_JUMP = 3  # tolerate a heading or two lost in extraction without rejecting everything after it
MAX_FIRST_NUMBER = 50


class _NumberingTracker:
    """Accepts a numbered line as a clause boundary only if it continues the
    document's numbering, so stray numbers (a wrapped "30. days", a list
    "1. 2. 3." nested inside clause 7) don't cut a clause in half.
    """

    def __init__(self):
        self.last_top: int | None = None

    def accept(self, num: str) -> bool:
        parts = [int(p) for p in num.split(".")]
        top = parts[0]
        if self.last_top is None:
            ok = 0 < top <= MAX_FIRST_NUMBER
        elif len(parts) > 1 and top == self.last_top:
            ok = True  # sub-clause of the current clause
        else:
            ok = self.last_top < top <= self.last_top + MAX_NUMBER_JUMP
        if ok:
            self.last_top = top
        return ok


def _starts_like_heading(rest: str) -> bool:
    rest = rest.strip()
    return not rest or rest[0] in ".:-–—)(\"“'" or rest[0].isupper() or rest[0].isdigit()


def _find_boundaries(lines: list[str]) -> list[int]:
    numbers = _NumberingTracker()
    sections = _NumberingTracker()
    boundaries = []
    for i, line in enumerate(lines):
        numbered = _NUMBERED_RE.match(line)
        if numbered:
            num = numbered.group("num")
            rest = numbered.group("rest_nodot")
            if rest is not None and "." not in num:
                continue  # "15 days notice..." — a bare number with no dot is not a clause number
            # clause text starts with a capital ("2. Term", "1.2 Fees"); a lowercase
            # start is a wrapped line ("4.2 hereof") or a list inside a clause ("2. keep it clean")
            if not _starts_like_heading(rest if rest is not None else numbered.group("rest") or ""):
                continue
            if numbers.accept(num):
                boundaries.append(i)
            continue

        article = _ARTICLE_RE.match(line)
        if article and _starts_like_heading(article.group("rest")):
            num = article.group("num")
            if not num[0].isdigit() or sections.accept(num):
                boundaries.append(i)
    return boundaries


def _is_caps_heading(line: str) -> bool:
    stripped = line.strip()
    letters = [ch for ch in stripped if ch.isalpha()]
    return (
        3 <= len(stripped) <= 60
        and len(letters) >= 3
        and all(ch.isupper() for ch in letters)
        and not stripped.endswith((".", ","))
    )


def _split_at(lines: list[str], boundaries: list[int]) -> list[Clause]:
    blocks: list[tuple[str | None, list[str]]] = []
    preamble = [line for line in lines[: boundaries[0]] if line.strip()]
    if preamble:
        blocks.append((PREAMBLE_HEADING, preamble))
    for idx, start in enumerate(boundaries):
        end = boundaries[idx + 1] if idx + 1 < len(boundaries) else len(lines)
        block = [line for line in lines[start:end] if line.strip()]
        if block:
            blocks.append((block[0].strip(), block))
    return [
        Clause(id=f"clause_{i + 1}", heading=heading, text="\n".join(block).strip())
        for i, (heading, block) in enumerate(blocks)
    ]


def _paragraphs(text: str) -> list[str]:
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text.strip()) if p.strip()]
    if len(paragraphs) == 1:
        lines = [line.strip() for line in paragraphs[0].splitlines() if line.strip()]
        # one paragraph per line (typical pasted text) vs. hard-wrapped prose:
        # in the first case most lines end a sentence, in the second most don't
        if len(lines) > 1 and sum(line.endswith(_SENTENCE_END) for line in lines) >= len(lines) / 2:
            return lines
    return paragraphs


def split_clauses(text: str) -> list[Clause]:
    """Rule-based clause splitting, in order of preference:
    1. numbered clauses / SECTION and ARTICLE headings that follow the
       document's numbering (anything before the first one is kept as a
       "Preamble" clause — it usually names the parties);
    2. ALL-CAPS headings, for unnumbered contracts;
    3. paragraphs.
    Every non-blank line of `text` ends up in exactly one clause.
    """
    lines = [line.rstrip() for line in text.strip().splitlines()]
    if not any(line.strip() for line in lines):
        return []

    boundaries = _find_boundaries(lines)
    if boundaries:
        return _split_at(lines, boundaries)

    caps = [i for i, line in enumerate(lines) if _is_caps_heading(line)]
    if len(caps) >= 2:
        return _split_at(lines, caps)

    return [
        Clause(id=f"clause_{i + 1}", heading=None, text=paragraph)
        for i, paragraph in enumerate(_paragraphs(text))
    ]
