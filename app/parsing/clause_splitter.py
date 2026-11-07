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

# "(Translation, for reference only)   1.2 Covenants of Parties" — page debris left on the same line as a
# heading. Only dotted numbers and ARTICLE/SECTION, after a run of spaces: a bare "  3 " is usually a table column.
_EMBEDDED_HEADING_RE = re.compile(
    r"[ \t]{3,}(?=(?:\d{1,3}\.\d{1,3}(?:\.\d{1,3})*\.?|(?i:ARTICLE|SECTION)\s+\d{1,3})\s+[A-Z])"
)
# "...CONDITIONS: 1. The Principal appoints ... agreement. 2. The Principal grants ..." — a contract
# whose clauses run on inside long paragraphs
_INLINE_NUMBER_RE = re.compile(r"(?<=[.;:])\s+(?=(\d{1,2})\.\s+[A-Z])")
_LINE_START_NUMBER_RE = re.compile(r"^\s*(\d{1,3})(?:\.\d{1,3})*[.)]?\s+[A-Z]")
MIN_RUN_ON_LINE = 200  # only lines this long are searched for inline clause numbers

# What follows the last clause: annexures/schedules ("ANNEXURE-I", "Schedule 2 Rent Payable") and the
# signature section ("IN WITNESS WHEREOF ...", "WITNESSES:", "Signed by"). Without these, all of it
# ended up inside the last clause. The annexure word must be in capitals, or start a title line
# ("Exhibit A", "Schedule 2 Rent Payable"), so a wrapped "Exhibit A and the Customer shall" is not one.
_ANNEX_CAPS_RE = re.compile(r"^\s*(?:ANNEXURE|ANNEX|SCHEDULE|APPENDIX|EXHIBIT)\b")
_ANNEX_TITLE_RE = re.compile(r"^\s*(?:Annexure|Annex|Schedule|Appendix|Exhibit)[\s\-‐-―:]*(?:[IVXLC]+|\d{1,3}|[A-Z])\b")
_SIGNATURE_RE = re.compile(
    r"^\s*(?:IN\s+WITNESS\s+WHERE(?:OF|AS)|WITNESS(?:ES)?\s*:|SIGNED\b|Signed\s+(?:and\s+delivered\s+)?(?:by|for)\b)",
    re.IGNORECASE,
)


class _NumberingTracker:
    """Accepts a numbered line as a clause boundary only if it continues the
    document's numbering, so stray numbers (a wrapped "30. days", a list
    "1. 2. 3." nested inside clause 7) don't cut a clause in half.
    """

    def __init__(self):
        self.last_top: int | None = None
        self.last: list[int] | None = None

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
            self.last = parts
        return ok

    def is_next_sub_clause(self, num: str) -> bool:
        """3.1 right after heading 3, or 3.2 right after 3.1: the exact next
        number, so it can start lowercase ("3.1 plan_b will ...") without
        risking a wrapped "4.2 hereof" being taken for a clause."""
        parts = [int(p) for p in num.split(".")]
        if self.last is None or len(parts) != 2:
            return False
        top, sub = parts
        last_top, last_sub = self.last[0], (self.last[1] if len(self.last) > 1 else 0)
        return (top == last_top and sub == last_sub + 1) or (top == last_top + 1 and sub == 1)


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
            if rest is not None and "." not in num and not _is_caps_heading(rest):
                continue  # "15 days notice..." — a bare number is a clause number only before a heading ("1    PURPOSE")
            # clause text starts with a capital ("2. Term", "1.2 Fees"); a lowercase start is
            # a wrapped line ("4.2 hereof") or a list inside a clause ("2. keep it clean") —
            # unless it is exactly the next sub-clause and the previous line is finished
            text = rest if rest is not None else numbered.group("rest") or ""
            if not _starts_like_heading(text) and not (
                _previous_line_finished(lines, i) and numbers.is_next_sub_clause(num)
            ):
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


def _back_matter_boundaries(lines: list[str], after: int) -> list[int]:
    """Annexures and the signature section after line `after` (the last clause's
    first line). Each annexure starts a block; the signature section starts one
    block that runs on (WITNESSES, names, signatures) until the next annexure."""
    boundaries = []
    in_signatures = False
    for i in range(after + 1, len(lines)):
        if _ANNEX_CAPS_RE.match(lines[i]) or (_ANNEX_TITLE_RE.match(lines[i]) and is_heading_only(lines[i])):
            boundaries.append(i)
            in_signatures = False
        elif not in_signatures and _SIGNATURE_RE.match(lines[i]):
            boundaries.append(i)
            in_signatures = True
    return boundaries


_SEGMENT_SPLIT_RE = re.compile(r"\n|(?<=[.;:])\s+(?=[A-Z(])")
MIN_PROSE_WORDS = 10


def _is_prose(segment: str) -> bool:
    # a sentence, not "(Name of the Witness)", "AMERICAN INTERNATIONAL GROUP, INC." or "By: /s/ ..."
    words = segment.split()
    return len(words) >= MIN_PROSE_WORDS and sum(w[0].islower() for w in words) >= MIN_PROSE_WORDS // 2


def is_signature_block(text: str) -> bool:
    """The execution and witness section with nothing to simplify: the "IN WITNESS
    WHEREOF the parties have signed" formula, then only names, titles and signature
    lines. A section that goes on to say something ("The undersigned Trustee has
    signed not individually ...") is a clause and is simplified like one."""
    if not _SIGNATURE_RE.match(text):
        return False
    # the formula runs to its first full stop or colon, often wrapped over lines
    formula_end = re.search(r"[.:](?=\s|$)", text)
    rest = text[formula_end.end() :] if formula_end else ""
    return not any(_is_prose(s) for s in _SEGMENT_SPLIT_RE.split(rest) if s.strip())


def _previous_line_finished(lines: list[str], i: int) -> bool:
    previous = lines[i - 1].strip() if i > 0 else ""
    return not previous or previous.endswith(_SENTENCE_END) or _is_caps_heading(previous)


def _split_run_on_lines(lines: list[str]) -> list[str]:
    """Puts each clause number at the start of its own line: after page debris
    on the same line, and inside run-on paragraphs — there only when the
    number is exactly the next one in sequence ("... agreement. 2. The ..."),
    so a "Section 2. The" or a date like "March 18. 2021" doesn't split.
    Only whitespace between the pieces is dropped.
    """
    out: list[str] = []
    last: int | None = None
    for line in lines:
        for piece in _EMBEDDED_HEADING_RE.split(line):
            start = _LINE_START_NUMBER_RE.match(piece)
            if start and (last is None or last < int(start.group(1)) <= last + MAX_NUMBER_JUMP):
                last = int(start.group(1))
            if len(piece) < MIN_RUN_ON_LINE:
                out.append(piece)
                continue
            cut = 0
            for match in _INLINE_NUMBER_RE.finditer(piece):
                number = int(match.group(1))
                if number == (last or 0) + 1:
                    out.append(piece[cut : match.start()])
                    cut = match.end()
                    last = number
            out.append(piece[cut:])
    return out


_HEADING_NUMBER_PREFIX_RE = re.compile(
    r"^\s*(?:(?:section|article|clause)\s+)?(?:\d{1,3}(?:\.\d{1,3})*|[IVXLC]+)\.?\s*", re.IGNORECASE
)
_SMALL_WORDS = {"of", "and", "the", "to", "for", "in", "on", "a", "an", "or", "with", "by", "&"}


def is_heading_only(text: str) -> bool:
    """A clause that is only a title — "4    REVENUES", "Article 2 Term of Agreement" —
    with nothing to simplify. One short line, no sentence ending, and every word
    after the number capitalised (small words aside), so a one-line clause like
    "5. Rent is due monthly" is not mistaken for a heading.
    """
    text = text.strip()
    if "\n" in text or len(text) > 80 or text.endswith((".", ";", ":", ",")):
        return False
    words = _HEADING_NUMBER_PREFIX_RE.sub("", text).split()
    return bool(words) and all(w[0].isupper() or not w[0].isalpha() or w.lower() in _SMALL_WORDS for w in words)


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
    In 1 and 2, annexures and the signature section after the last clause
    become blocks of their own.
    Every word of `text` ends up in exactly one clause, in order (a line may
    be split where a clause number sits mid-line).
    """
    lines = _split_run_on_lines([line.rstrip() for line in text.strip().splitlines()])
    if not any(line.strip() for line in lines):
        return []

    boundaries = _find_boundaries(lines)
    if boundaries:
        return _split_at(lines, boundaries + _back_matter_boundaries(lines, boundaries[-1]))

    caps = [i for i, line in enumerate(lines) if _is_caps_heading(line)]
    if len(caps) >= 2:
        return _split_at(lines, sorted(set(caps + _back_matter_boundaries(lines, caps[-1]))))

    return [
        Clause(id=f"clause_{i + 1}", heading=None, text=paragraph)
        for i, paragraph in enumerate(_paragraphs(text))
    ]
