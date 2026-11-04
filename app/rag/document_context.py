import re
from dataclasses import dataclass, field

from app.models.schemas import Clause, ClauseContext
from app.parsing.clause_splitter import PREAMBLE_HEADING

MAX_CONTEXT_CHARS = 1500  # per clause, across parties + definitions + referenced sections
MAX_DEFINITION_CHARS = 300
MAX_SECTION_CHARS = 600
PREAMBLE_FALLBACK_CHARS = 2000  # where to look for parties when the document has no numbered clauses

# Words whose abbreviation dot is not a sentence end ("No. 302", "Rs. 500", "Pvt. Ltd.", "Dr.")
_ABBREVIATIONS = ("no", "nos", "rs", "pvt", "ltd", "co", "inc", "corp", "mr", "mrs", "ms", "dr", "st", "sr", "jr")
_NOT_AFTER_ABBREVIATION = "".join(rf"(?<!\b(?i:{abbr}))" for abbr in _ABBREVIATIONS)

_OPEN_QUOTE = "\"“'‘"
_CLOSE_QUOTE = "\"”'’"
_TERM = rf"[{_OPEN_QUOTE}](?P<term>[A-Z][^{_CLOSE_QUOTE}\n]{{0,59}})[{_CLOSE_QUOTE}]"

# "Services" means ... / "Fee" shall mean ... / 'Premises' includes ...
_MEANS_RE = re.compile(
    rf"{_TERM}\s+(?:shall\s+)?(?:means?|refers?\s+to|includes?)\s+"
    rf"(?P<definition>.+?)(?={_NOT_AFTER_ABBREVIATION}[.;](?:\s|$)|\n\s*\n|$)",
    re.DOTALL,
)
# "Goods" means:  followed by a list — runs to a blank line or the next quoted definition
_LIST_MEANS_RE = re.compile(
    rf"{_TERM}\s+(?:shall\s+)?(?:means?|includes?)\s*:\s*"
    rf"(?P<definition>.+?)(?=\n\s*\n|\n\s*[{_OPEN_QUOTE}][A-Z]|$)",
    re.DOTALL,
)
# "Term" has the meaning given to it in Clause 3 — the definition is that clause
_POINTER_RE = re.compile(
    rf"{_TERM}\s+(?:shall\s+)?ha(?:s|ve)\s+the\s+meaning\s+(?:given|assigned|ascribed|set\s+out)\s+"
    r"(?:to\s+it\s+)?in\s+(?:clause|section|article)\s+(?P<number>\d+(?:\.\d+)*)",
    re.IGNORECASE,
)
# Acme Ltd, a company ... (the "Provider") / ... (hereinafter referred to as "Client");
# short markers like "twelve (12) months" or "(a)" may sit inside the subject
_INLINE_RE = re.compile(
    r"(?P<subject>(?:[^()]|\([0-9a-z]{1,3}\)){2,160}?)\s*\(\s*(?:[Hh]ereinafter\s+(?:referred\s+to\s+as\s+|called\s+)?)?"
    rf"(?:[Tt]he\s+)?{_TERM}\s*\)"
)
# Section 7 / clause 4.2 / Clauses 5, 6 and 9 / Clauses 3 to 5 / Section 5(b) — but not
# "Section 7 of the Schedule" or "paragraphs 2 to 3 of Schedule B", which are outside this document's numbering
_NUMBER = r"\d+(?:\.\d+)*(?:\s*\([a-z0-9]+\))*"
_REFERENCE_RE = re.compile(
    # atomic group: the whole list is checked against "of the Schedule", so "2 to 3 of Schedule B" can't backtrack to "2"
    rf"\b(?:sections?|clauses?|sub-clauses?|articles?|paragraphs?)\s+(?P<numbers>(?>{_NUMBER}(?:\s*(?:,|and|or|to|&)\s*{_NUMBER})*))"
    r"(?!\s+of\s+(?:the\s+|this\s+)?(?:schedule|annex|annexure|exhibit|appendix))",
    re.IGNORECASE,
)
_RANGE_RE = re.compile(r"\b(\d+)\s*to\s*(\d+)\b")
MAX_RANGE = 20
_HEADING_NUMBER_RE = re.compile(r"^\s*(?:(?:SECTION|ARTICLE)\s+)?(\d+(?:\.\d+)*)\b", re.IGNORECASE)


def _collapse(text: str) -> str:
    return " ".join(text.split())


def _truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


# "between", a clause heading line ("2. Commencement"), or a sentence break that
# isn't the dot of a name abbreviation ("Pvt. Ltd.", "Mr.") or initial ("A. Rao")
_SUBJECT_BREAK_RE = re.compile(
    r"\bbetween\b|(?m:^[ \t]*\d+(?:\.\d+)*\.?[ \t]+[^\n]{0,80}\n)|[;:]\s|"
    + _NOT_AFTER_ABBREVIATION
    + r"(?<!\b[a-z])\.\s",
    re.IGNORECASE,
)


def _clean_subject(subject: str) -> str:
    """Trim the text before an inline definition down to the thing being
    defined: drop everything up to the last "between" or sentence break,
    and a leading "and" (the second party in "between A (...), and B (...)").
    """
    subject = _SUBJECT_BREAK_RE.split(subject)[-1]
    subject = re.sub(r"^[\s,]*and\b", "", subject, flags=re.IGNORECASE)
    return _collapse(subject).strip(" ,")


def _uses_term(text: str, term: str) -> bool:
    """Defined terms are used in the plural and possessive too ("Business Days", "Supplier's")."""
    return re.search(rf"\b{re.escape(term)}(?:s|es)?(?:['’]s?)?\b", text) is not None


def _defines_term(text: str, term: str) -> bool:
    """A clause that puts the term in quotes is defining it (or pointing to its
    definition), so it doesn't need the definition handed back as context.
    """
    return re.search(rf"[{_OPEN_QUOTE}]{re.escape(term)}[{_CLOSE_QUOTE}]", text) is not None


def _referenced_numbers(numbers: str) -> list[str]:
    """ "5, 6 and 9" -> 5, 6, 9 / "3 to 5" -> 3, 4, 5 / "5(b)" -> 5."""
    found: list[str] = []
    for start, end in _RANGE_RE.findall(numbers):
        if int(start) < int(end) <= int(start) + MAX_RANGE:
            found.extend(str(n) for n in range(int(start), int(end) + 1))
    found.extend(re.findall(r"\d+(?:\.\d+)*", numbers))
    return list(dict.fromkeys(found))


@dataclass
class DocumentContext:
    parties: list[str] = field(default_factory=list)
    definitions: dict[str, str] = field(default_factory=dict)
    sections: dict[str, Clause] = field(default_factory=dict)


def _preamble_end(text: str, clauses: list[Clause]) -> int:
    first_heading = next((c.heading for c in clauses if c.heading and c.heading != PREAMBLE_HEADING), None)
    if first_heading:
        position = text.find(first_heading)
        if position >= 0:
            return position
    return min(len(text), PREAMBLE_FALLBACK_CHARS)


def build_document_context(text: str, clauses: list[Clause]) -> DocumentContext:
    """Index the whole extracted text (not just the clauses, so a preamble
    the splitter skipped still contributes its parties and definitions).
    The first definition of a term wins.
    """
    context = DocumentContext()
    preamble_end = _preamble_end(text, clauses)

    for clause in clauses:
        number = _HEADING_NUMBER_RE.match(clause.heading or "")
        if number:
            context.sections.setdefault(number.group(1), clause)

    for match in sorted(
        [
            *_MEANS_RE.finditer(text),
            *_LIST_MEANS_RE.finditer(text),
            *_POINTER_RE.finditer(text),
            *_INLINE_RE.finditer(text),
        ],
        key=lambda m: m.start("term"),
    ):
        term = match.group("term").strip()
        if term in context.definitions or any(p.startswith(f"{term}: ") for p in context.parties):
            continue
        if match.re is _POINTER_RE:
            resolved = _resolve_section(match.group("number"), context.sections)
            if resolved is not None:
                number, section = resolved
                context.definitions[term] = _truncate(
                    f"{term}: as defined in Clause {number}: {_collapse(section.text)}", MAX_DEFINITION_CHARS
                )
            continue  # unresolvable pointer: a later inline definition can still supply it
        if match.re is not _INLINE_RE:
            context.definitions[term] = _truncate(_collapse(match.group(0)), MAX_DEFINITION_CHARS)
            continue
        subject = _clean_subject(match.group("subject"))
        if not subject:
            continue
        entry = _truncate(f"{term}: {subject}", MAX_DEFINITION_CHARS)
        if match.start("term") < preamble_end:
            context.parties.append(entry)
        else:
            context.definitions[term] = entry

    return context


def _resolve_section(number: str, sections: dict[str, Clause]) -> tuple[str, Clause] | None:
    """Sub-clauses (4.2) usually live inside their parent clause (4), so fall
    back up the numbering until something matches.
    """
    while number:
        if number in sections:
            return number, sections[number]
        number = number.rpartition(".")[0]
    return None


def retrieve_clause_context(clause: Clause, context: DocumentContext) -> ClauseContext | None:
    """Parties first (always relevant, short), then definitions of terms the
    clause actually uses, then sections it refers to — until the budget runs out.
    """
    result = ClauseContext()
    budget = MAX_CONTEXT_CHARS
    clause_text = _collapse(clause.text)

    for party in context.parties if clause.heading != PREAMBLE_HEADING else []:  # the preamble names them itself
        if len(party) > budget:
            break
        result.parties.append(party)
        budget -= len(party)

    for term, definition in context.definitions.items():
        if definition in clause_text or _defines_term(clause.text, term) or not _uses_term(clause.text, term):
            continue  # skip the clause that defines the term, and terms the clause never uses
        if len(definition) > budget:
            continue
        result.definitions[term] = definition
        budget -= len(definition)

    referenced = [n for match in _REFERENCE_RE.finditer(clause.text) for n in _referenced_numbers(match.group("numbers"))]
    for reference in referenced:
        resolved = _resolve_section(reference, context.sections)
        if resolved is None:
            continue
        number, section = resolved
        if section.id == clause.id or number in result.referenced_sections:
            continue
        if budget < 50:
            break
        section_text = _truncate(_collapse(section.text), min(MAX_SECTION_CHARS, budget))
        result.referenced_sections[number] = section_text
        budget -= len(section_text)

    if not (result.parties or result.definitions or result.referenced_sections):
        return None
    return result


def attach_context(text: str, clauses: list[Clause]) -> list[Clause]:
    context = build_document_context(text, clauses)
    return [
        clause.model_copy(update={"context": retrieve_clause_context(clause, context)})
        for clause in clauses
    ]
