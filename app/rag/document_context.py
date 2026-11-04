import re
from dataclasses import dataclass, field

from app.models.schemas import Clause, ClauseContext
from app.parsing.clause_splitter import PREAMBLE_HEADING

MAX_CONTEXT_CHARS = 1500  # per clause, across parties + definitions + referenced sections
MAX_DEFINITION_CHARS = 300
MAX_SECTION_CHARS = 600
PREAMBLE_FALLBACK_CHARS = 2000  # where to look for parties when the document has no numbered clauses

# "Services" means ... / "Fee" shall mean ... / "Premises" includes ...
_MEANS_RE = re.compile(
    r"[\"“](?P<term>[A-Z][^\"”\n]{0,59})[\"”]\s+(?:shall\s+)?(?:means?|refers?\s+to|includes?)\s+"
    r"(?P<definition>.+?)(?=[.;](?:\s|$)|\n\s*\n|$)",
    re.DOTALL,
)
# Acme Ltd, a company ... (the "Provider") / ... (hereinafter referred to as "Client")
_INLINE_RE = re.compile(
    r"(?P<subject>[^()]{2,160}?)\s*\(\s*(?:[Hh]ereinafter\s+(?:referred\s+to\s+as\s+|called\s+)?)?"
    r"(?:[Tt]he\s+)?[\"“](?P<term>[A-Z][^\"”\n]{0,59})[\"”]\s*\)"
)
# Section 7 / clause 4.2 / Article 3 — but not "Section 7 of the Schedule", which is outside this document's numbering
_REFERENCE_RE = re.compile(
    r"\b(?:sections?|clauses?|articles?|paragraphs?)\s+(\d+(?:\.\d+)*)"
    r"(?!\s+of\s+(?:the\s+|this\s+)?(?:schedule|annex|annexure|exhibit|appendix))",
    re.IGNORECASE,
)
_HEADING_NUMBER_RE = re.compile(r"^\s*(?:(?:SECTION|ARTICLE)\s+)?(\d+(?:\.\d+)*)\b", re.IGNORECASE)


def _collapse(text: str) -> str:
    return " ".join(text.split())


def _truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


# "between", or a sentence break that isn't the dot of a name abbreviation ("Pvt. Ltd.", "Mr.") or initial ("A. Rao")
_SUBJECT_BREAK_RE = re.compile(
    r"\bbetween\b|[;:]\s|"
    + "".join(rf"(?<!\b{abbr})" for abbr in ("pvt", "ltd", "co", "inc", "corp", "mr", "mrs", "ms", "dr", "no", "st"))
    + r"(?<!\b[a-z])\.\s",
    re.IGNORECASE,
)


def _clean_subject(subject: str) -> str:
    """Trim the text before an inline definition down to the thing being
    defined: drop everything up to the last "between" or sentence break,
    and a leading "and" (the second party in "between A (...) and B (...)").
    """
    subject = _SUBJECT_BREAK_RE.split(subject)[-1]
    subject = re.sub(r"^\s*and\b", "", subject, flags=re.IGNORECASE)
    return _collapse(subject).strip(" ,")


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

    for match in sorted(
        [*_MEANS_RE.finditer(text), *_INLINE_RE.finditer(text)], key=lambda m: m.start("term")
    ):
        term = match.group("term").strip()
        if term in context.definitions or any(p.startswith(f"{term}: ") for p in context.parties):
            continue
        if match.re is _MEANS_RE:
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

    for clause in clauses:
        number = _HEADING_NUMBER_RE.match(clause.heading or "")
        if number:
            context.sections.setdefault(number.group(1), clause)

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
        if definition in clause_text or not re.search(rf"\b{re.escape(term)}\b", clause.text):
            continue  # skip the clause that defines the term, and terms the clause never uses
        if len(definition) > budget:
            continue
        result.definitions[term] = definition
        budget -= len(definition)

    for match in _REFERENCE_RE.finditer(clause.text):
        resolved = _resolve_section(match.group(1), context.sections)
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
