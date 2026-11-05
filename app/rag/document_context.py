import re
from dataclasses import dataclass, field

from app.models.schemas import Clause, ClauseContext
from app.parsing.clause_splitter import PREAMBLE_HEADING

MAX_CONTEXT_CHARS = 1500  # per clause, across parties + definitions + referenced sections
MAX_PARTY_CHARS = 160  # a party's name matters; its full address doesn't
MAX_DEFINITION_CHARS = 300
MAX_SECTION_CHARS = 600
MIN_SECTION_CHARS = 150  # when several sections are referenced, each gets an equal share, but at least this
MAX_UNMENTIONED_PARTIES = 4  # up to this many, every clause gets every party; beyond it, only the ones it names
PREAMBLE_FALLBACK_CHARS = 2000  # where to look for parties when the document has no numbered clauses

# Words whose abbreviation dot is not a sentence end ("No. 302", "Rs. 500", "Pvt. Ltd.", "Dr.")
_ABBREVIATIONS = ("no", "nos", "rs", "pvt", "ltd", "co", "inc", "corp", "mr", "mrs", "ms", "dr", "st", "sr", "jr")
_NOT_AFTER_ABBREVIATION = "".join(rf"(?<!\b(?i:{abbr}))" for abbr in _ABBREVIATIONS)

_OPEN_QUOTE = "\"“'‘"
_CLOSE_QUOTE = "\"”'’"
# an apostrophe followed by a letter is part of the term ("Moody's"), not its closing quote
_TERM_BODY = rf"[A-Z](?:[^{_CLOSE_QUOTE}\n]|['’](?=[A-Za-z])){{0,59}}"
_TERM = rf"[{_OPEN_QUOTE}](?P<term>{_TERM_BODY})[{_CLOSE_QUOTE}]"
_SENTENCE_END = rf"(?={_NOT_AFTER_ABBREVIATION}[.;](?:\s|$)|\n\s*\n|$)"

# The document naming itself is not a definition worth sending with every clause
_SELF_REFERENCES = {"agreement", "amendment", "contract", "addendum", "deed", "letter agreement"}

# "Services" means ... / "Fee" shall mean ... / 'Premises' includes ...
_MEANS_RE = re.compile(
    rf"{_TERM}\s+(?:shall\s+)?(?:means?|refers?\s+to|includes?)\s+(?P<definition>.+?){_SENTENCE_END}",
    re.DOTALL,
)
# "Goods" means:  followed by a list — runs to a blank line or the next quoted definition
_LIST_MEANS_RE = re.compile(
    rf"{_TERM}\s+(?:shall\s+)?(?:means?|includes?)\s*:\s*"
    rf"(?P<definition>.+?)(?=\n\s*\n|\n\s*[{_OPEN_QUOTE}][A-Z]|$)",
    re.DOTALL,
)
# 1.2  End User means ...  (unquoted, at the start of a clause or line)
_UNQUOTED_MEANS_RE = re.compile(
    r"^[ \t]*(?:\d+(?:\.\d+)*\.?[ \t]+)?(?P<term>(?!(?:This|The|Each|Any|It|Such)\b)[A-Z][A-Za-z]+(?:[ \t]+[A-Z][A-Za-z]+){0,4})"
    rf"\s+(?:shall\s+)?means\s+(?P<definition>.+?){_SENTENCE_END}",
    re.MULTILINE | re.DOTALL,
)
# the terms "Total Adjusted Capital" and "Company Action Level RBC" shall have the meanings ... /
# The term "Specified Minimum Percentage" shall be equal to ... — the whole sentence is the definition
_QUOTED = rf"[{_OPEN_QUOTE}]{_TERM_BODY}[{_CLOSE_QUOTE}]"
_TERMS_SENTENCE_RE = re.compile(
    rf"\b(?:the\s+)?terms?\s+(?P<terms>{_QUOTED}(?:\s*(?:,|and)\s*{_QUOTED})*)\s+"
    rf"(?:shall\s+)?(?:have|has|mean|means|be|is|are|refers?)\b.+?{_SENTENCE_END}",
    re.IGNORECASE | re.DOTALL,
)
# "Term" has the meaning given to it in Clause 3 — the definition is that clause
_POINTER_RE = re.compile(
    rf"{_TERM}\s+(?:shall\s+)?ha(?:s|ve)\s+the\s+meaning\s+(?:given|assigned|ascribed|set\s+out)\s+"
    r"(?:to\s+it\s+)?in\s+(?:clause|section|article)\s+(?P<number>\d+(?:\.\d+)*)",
    re.IGNORECASE,
)
# Acme Ltd, a company ... (the "Provider") / ... (hereinafter referred to as "Client") /
# ... ("VNBJ SPA," and ...) — short markers like "twelve (12) months", "(a)" or "(Zhongshan)" may sit inside the subject
_SUBJECT = r"(?P<subject>(?:[^()]|\([0-9a-z]{1,3}\)|\([A-Z][A-Za-z ]{1,20}\)){2,160}?)"
_INLINE_RE = re.compile(
    rf"{_SUBJECT}\s*\(\s*(?:[Hh]ereinafter\s+(?:referred\s+to\s+as\s+|called\s+)?)?"
    rf"(?:[Tt]he\s+)?{_TERM}\s*(?:\)|,?\s*and\b)"
)
# ("Veoneer US" and together with Veoneer AB, the "Veoneer Parties") /
# (the "VNBJ SPA," and the consummation of ..., the "VNBJ Closing") — the second term in one bracket
_SECOND_IN_BRACKET_RE = re.compile(
    rf"[{_OPEN_QUOTE}](?P<first>{_TERM_BODY})[{_CLOSE_QUOTE}],?\s*and\s+(?P<together>together\s+with\s+)?"
    rf"(?P<subject>[^()\"“]{{1,200}}?),\s*(?:[Tt]he\s+)?{_TERM}\s*\)"
)
# Data Call Technologies, Inc. ... hereinafter referred to as "Licensor"   (no brackets)
_HEREINAFTER_RE = re.compile(
    rf"(?P<subject>[^\"“”()]{{2,300}}?)\s*,?\s*hereinafter\s+(?:referred\s+to\s+as|called)\s+(?:the\s+)?{_TERM}",
    re.IGNORECASE,
)
# Section 7 / clause 4.2 / Clauses 5, 6 and 9 / Clauses 3 to 5 / Section 5(b) — but not references into
# another document: "Section 7 of the Schedule", "Sections 4.3.2 and 4.3.3 of the JV Agreement",
# "paragraph 8 of Statement ... No. 72". Only "of this Agreement" stays inside this document.
_NUMBER = r"\d+(?:\.\d+)*(?:\s*\([a-z0-9]+\))*"
_REFERENCE_RE = re.compile(
    # atomic group: the whole list is checked against "of ...", so "2 to 3 of Schedule B" can't backtrack to "2"
    rf"\b(?:sections?|clauses?|sub-clauses?|articles?|paragraphs?)\s+(?P<numbers>(?>{_NUMBER}(?:\s*(?:,|and|or|to|&)\s*{_NUMBER})*))"
    r"(?!\s+of\s+(?!this\s+(?:agreement|amendment|contract|addendum|deed)\b))",
    re.IGNORECASE,
)
_RANGE_RE = re.compile(r"\b(\d+)\s*to\s*(\d+)\b")
MAX_RANGE = 20
_HEADING_NUMBER_RE = re.compile(r"^\s*(?:(?:SECTION|ARTICLE)\s+)?(\d+(?:\.\d+)*)\b", re.IGNORECASE)

# Parties are named in the opening words, before the recitals start
_RECITALS_START_RE = re.compile(r"\b(?:WHEREAS|RECITALS|BACKGROUND|NOW,?\s+THEREFORE|IT\s+IS\s+(?:HEREBY\s+)?AGREED)\b")
# A party is a person or an organisation, not "Effective Date: is made ... as of October 30, 2019"
_ORGANISATION_RE = re.compile(
    r"\b(?:Inc|Ltd|LLC|LLP|L\.P|AG|GmbH|Corp|Corporation|Company|Co|Limited|plc|PLC|S\.A|N\.V|B\.V|AB|SE|Pvt|Bank|"
    r"Trust|University|Foundation|Association)\b\.?|\b(?:individual|residing|resident|trading\s+as)\b|\b(?:Mr|Mrs|Ms|Dr)\.",
)
_NAME_LIKE_RE = re.compile(r"^(?:[A-Z][\w.&'’-]*\s+){1,4}[A-Z][\w.&'’-]*(?:,|$)")


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


def _hereinafter_subject(subject: str) -> str:
    """For a cover-page layout ("between / NAME ADDRESS / hereinafter referred to
    as ..."), the name is the last non-empty block before "hereinafter" that
    isn't just "and" or "between". Sentence dots ("Schaafenstr. 25") don't split it.
    """
    blocks = [_collapse(b) for b in re.split(r"\n\s*\n", subject)]
    blocks = [b for b in blocks if b and b.lower() not in ("and", "between", "by and between")]
    if not blocks:
        return ""
    block = re.split(r"\bbetween\b", blocks[-1], flags=re.IGNORECASE)[-1]
    return re.sub(r"^[\s,]*and\b", "", block, flags=re.IGNORECASE).strip(" ,")


def _is_party(subject: str) -> bool:
    return bool(_ORGANISATION_RE.search(subject) or _NAME_LIKE_RE.match(subject))


def _uses_term(text: str, term: str) -> bool:
    """Defined terms are used in the plural and possessive too ("Business Days", "Supplier's")."""
    return re.search(rf"\b{re.escape(term)}(?:s|es)?(?:['’]s?)?(?!\w)", text) is not None


def _defines_term(text: str, term: str) -> bool:
    """A clause that puts the term in quotes is defining it (or pointing to its
    definition), so it doesn't need the definition handed back as context.
    """
    return re.search(rf"[{_OPEN_QUOTE}]{re.escape(term)},?[{_CLOSE_QUOTE}]", text) is not None


def _without_longer_terms(text: str, term: str, terms) -> str:
    """"RBC" inside "Company Action Level RBC" is part of that term, not a use of "RBC"."""
    for other in terms:
        if other != term and term in other:
            text = text.replace(other, " ")
    return text


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


def _parties_end(text: str, preamble_end: int) -> int:
    recitals = _RECITALS_START_RE.search(text, 0, preamble_end)
    return recitals.start() if recitals else preamble_end


@dataclass
class _Candidate:
    position: int
    term: str
    definition: str | None = None  # full definition text, used as-is
    subject: str | None = None  # the thing an inline definition names: a party or a definition
    pointer: str | None = None  # clause number a "has the meaning given in Clause N" points to


def _candidates(text: str) -> list[_Candidate]:
    found: list[_Candidate] = []
    for regex in (_MEANS_RE, _LIST_MEANS_RE, _UNQUOTED_MEANS_RE):
        for m in regex.finditer(text):
            found.append(_Candidate(m.start("term"), m.group("term"), definition=_collapse(m.group(0))))
    for m in _TERMS_SENTENCE_RE.finditer(text):
        sentence = _collapse(m.group(0))
        for term in re.finditer(rf"[{_OPEN_QUOTE}]({_TERM_BODY})[{_CLOSE_QUOTE}]", m.group("terms")):
            found.append(_Candidate(m.start("terms") + term.start(), term.group(1), definition=sentence))
    for m in _POINTER_RE.finditer(text):
        found.append(_Candidate(m.start("term"), m.group("term"), pointer=m.group("number")))
    for m in _INLINE_RE.finditer(text):
        found.append(_Candidate(m.start("term"), m.group("term"), subject=_clean_subject(m.group("subject"))))
    for m in _SECOND_IN_BRACKET_RE.finditer(text):
        subject = _collapse(m.group("subject"))
        if m.group("together"):
            subject = f"{m.group('first').strip(' ,')} and {subject}"
        found.append(_Candidate(m.start("term"), m.group("term"), subject=subject))
    for m in _HEREINAFTER_RE.finditer(text):
        found.append(_Candidate(m.start("term"), m.group("term"), subject=_hereinafter_subject(m.group("subject"))))
    # stable sort: at the same position, the earlier pattern in the lists above wins
    return sorted(found, key=lambda c: c.position)


def build_document_context(text: str, clauses: list[Clause]) -> DocumentContext:
    """Index the whole extracted text (not just the clauses, so a preamble
    the splitter skipped still contributes its parties and definitions).
    The first definition of a term wins.
    """
    context = DocumentContext()
    preamble_end = _preamble_end(text, clauses)
    parties_end = _parties_end(text, preamble_end)
    party_terms: set[str] = set()

    for clause in clauses:
        number = _HEADING_NUMBER_RE.match(clause.heading or "")
        if number:
            context.sections.setdefault(number.group(1), clause)

    for candidate in _candidates(text):
        term = candidate.term.strip(" ,")
        if term.lower() in _SELF_REFERENCES or term in context.definitions or term in party_terms:
            continue
        if candidate.pointer is not None:
            resolved = _resolve_section(candidate.pointer, context.sections)
            if resolved is not None:
                number, section = resolved
                context.definitions[term] = _truncate(
                    f"{term}: as defined in Clause {number}: {_collapse(section.text)}", MAX_DEFINITION_CHARS
                )
            continue  # unresolvable pointer: a later inline definition can still supply it
        if candidate.definition is not None:
            context.definitions[term] = _truncate(candidate.definition, MAX_DEFINITION_CHARS)
            continue
        if not candidate.subject:
            continue
        if candidate.position < parties_end and _is_party(candidate.subject):
            context.parties.append(_truncate(f"{term}: {candidate.subject}", MAX_PARTY_CHARS))
            party_terms.add(term)
        else:
            context.definitions[term] = _truncate(f"{term}: {candidate.subject}", MAX_DEFINITION_CHARS)

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

    parties = context.parties if clause.heading != PREAMBLE_HEADING else []  # the preamble names them itself
    if len(parties) > MAX_UNMENTIONED_PARTIES:
        # many parties (group companies, a previous agreement's parties): only the ones this clause names
        parties = [p for p in parties if _uses_term(clause_text, p.split(": ", 1)[0])]
    for party in parties:
        if len(party) > budget:
            break
        result.parties.append(party)
        budget -= len(party)

    for term, definition in context.definitions.items():
        if definition in clause_text or _defines_term(clause_text, term):
            continue  # the clause that defines the term doesn't need it back
        if not _uses_term(_without_longer_terms(clause_text, term, context.definitions), term):
            continue
        if len(definition) > budget:
            continue
        result.definitions[term] = definition
        budget -= len(definition)

    sections: dict[str, Clause] = {}
    for match in _REFERENCE_RE.finditer(clause.text):
        for reference in _referenced_numbers(match.group("numbers")):
            resolved = _resolve_section(reference, context.sections)
            if resolved is not None and resolved[1].id != clause.id:
                sections.setdefault(*resolved)
    # several references share what is left, rather than the first one or two taking it all
    share = min(MAX_SECTION_CHARS, max(MIN_SECTION_CHARS, budget // len(sections))) if sections else 0
    for number, section in sections.items():
        if budget < 50:
            break
        section_text = _truncate(_collapse(section.text), min(share, budget))
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
