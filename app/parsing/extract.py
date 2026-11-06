import io
import re

import docx
import fitz  # PyMuPDF
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph

from app.constants import MAX_PDF_PAGES
from app.models.schemas import Clause
from app.parsing.clause_splitter import split_clauses


class ExtractionError(Exception):
    """Raised when a document cannot be parsed into usable text."""


class NoTextLayerError(ExtractionError):
    """Raised for PDFs with no extractable text layer (e.g. scanned pages)."""



# Running headers and footers sit in the top/bottom margin of the page
_MARGIN_FRACTION = 0.08
# "3", "- 3 -", "Page 3", "Page 3 of 10", "3/10" (no trailing dot, so a lone "3." heading survives)
_PAGE_NUMBER_RE = re.compile(r"^(?:page\s*)?[-–—]?\s*\d{1,4}\s*[-–—]?(?:\s*(?:of|/)\s*\d{1,4})?$", re.IGNORECASE)


def _running_key(text: str) -> str:
    """Page headers repeat with only the page number changing."""
    return re.sub(r"\d+", "#", " ".join(text.split())).lower()


def _in_margin(block, page_height: float) -> bool:
    return block[3] <= page_height * _MARGIN_FRACTION or block[1] >= page_height * (1 - _MARGIN_FRACTION)


def _remove_headers_and_footers(pages: list[tuple[list, float]]) -> list[list]:
    """Drops margin blocks that are page numbers or that repeat on two or
    more pages, so "Confidential - Page 3 of 12" isn't spliced into a clause.
    """
    margin_pages: dict[str, set[int]] = {}
    for index, (blocks, height) in enumerate(pages):
        for block in blocks:
            if _in_margin(block, height):
                margin_pages.setdefault(_running_key(block[4]), set()).add(index)

    def is_running(block, height) -> bool:
        if not _in_margin(block, height):
            return False
        text = " ".join(block[4].split())
        return bool(_PAGE_NUMBER_RE.match(text)) or len(margin_pages[_running_key(text)]) >= 2

    return [[b for b in blocks if not is_running(b, height)] for blocks, height in pages]


def _reading_order(blocks: list, page_width: float) -> list:
    """Columns are read one after the other only when the page really has
    them: some right-half block sits beside a left-half block. Otherwise a
    right-aligned date or signature line would be moved to the end of the page.
    """
    mid_x = page_width / 2
    left = [b for b in blocks if b[0] < mid_x]
    right = [b for b in blocks if b[0] >= mid_x]
    side_by_side = any(r[1] < l[3] and l[1] < r[3] for r in right for l in left)
    if side_by_side:
        return sorted(blocks, key=lambda b: (0 if b[0] < mid_x else 1, round(b[1], 1)))
    return sorted(blocks, key=lambda b: (round(b[1], 1), b[0]))


def extract_pdf(content: bytes) -> str:
    try:
        doc = fitz.open(stream=content, filetype="pdf")
        try:
            if doc.page_count > MAX_PDF_PAGES:
                raise ExtractionError(
                    f"The PDF has {doc.page_count} pages; the limit is {MAX_PDF_PAGES}. "
                    "Split it into smaller files and upload them separately."
                )
            pages = []
            for page in doc:
                blocks = [
                    b for b in page.get_text("blocks")
                    if b[6] == 0 and b[4].strip()
                ]
                pages.append((blocks, page.rect.height, page.rect.width))
        finally:
            doc.close()

    except ExtractionError:
        raise
    except Exception as e:
        raise ExtractionError(
            "Could not read the PDF. The file may be damaged or unsupported."
        ) from e

    cleaned = _remove_headers_and_footers([(blocks, height) for blocks, height, _ in pages])
    page_texts = [
        "\n\n".join(b[4].strip() for b in _reading_order(blocks, width))
        for blocks, (_, _, width) in zip(cleaned, pages)
    ]
    text = "\n\n".join(t for t in page_texts if t).strip()
    if not text:
        raise NoTextLayerError(
            "PDF has no extractable text layer "
            "(likely a scanned document); OCR is out of scope for MVP"
        )
    return text


_DECIMAL_FORMATS = {"decimal", "decimalZero"}


def _to_roman(n: int) -> str:
    numerals = [(10, "x"), (9, "ix"), (5, "v"), (4, "iv"), (1, "i")]
    out = ""
    for value, numeral in numerals:
        while n >= value:
            out += numeral
            n -= value
    return out


def _numbering_formats(document) -> dict[tuple[str, int], str]:
    """(numId, level) -> Word number format ("decimal", "lowerLetter", "bullet", ...)."""
    numbering = document.part.numbering_part.element
    abstract_formats: dict[tuple[str, int], str] = {}
    for abstract in numbering.findall(qn("w:abstractNum")):
        abstract_id = abstract.get(qn("w:abstractNumId"))
        for level in abstract.findall(qn("w:lvl")):
            fmt = level.find(qn("w:numFmt"))
            abstract_formats[(abstract_id, int(level.get(qn("w:ilvl"))))] = (
                fmt.get(qn("w:val")) if fmt is not None else "decimal"
            )
    formats: dict[tuple[str, int], str] = {}
    for num in numbering.findall(qn("w:num")):
        abstract_ref = num.find(qn("w:abstractNumId"))
        if abstract_ref is None:
            continue
        for (abstract_id, level), fmt in abstract_formats.items():
            if abstract_id == abstract_ref.get(qn("w:val")):
                formats[(num.get(qn("w:numId")), level)] = fmt
    return formats


def _num_pr(paragraph: Paragraph):
    """Auto-numbering can sit on the paragraph or on its style (e.g. "List Number")."""
    p_pr = paragraph._p.pPr
    if p_pr is not None and p_pr.numPr is not None:
        return p_pr.numPr
    style = paragraph.style
    while style is not None:
        s_pr = style.element.pPr
        if s_pr is not None and s_pr.numPr is not None:
            return s_pr.numPr
        style = style.base_style
    return None


class _ListNumberer:
    """Reconstructs the visible number of auto-numbered Word paragraphs.
    `paragraph.text` omits it, so without this a numbered DOCX contract has
    no "1." / "2." lines and can't be split into clauses.
    """

    def __init__(self, formats: dict[tuple[str, int], str]):
        self._formats = formats
        self._counters: dict[str, list[int]] = {}

    def prefix(self, paragraph: Paragraph) -> str:
        num_pr = _num_pr(paragraph)
        if num_pr is None or num_pr.numId is None or num_pr.numId.val == 0:
            return ""
        num_id = str(num_pr.numId.val)
        level = num_pr.ilvl.val if num_pr.ilvl is not None else 0
        fmt = self._formats.get((num_id, level), "decimal")

        counters = self._counters.setdefault(num_id, [0] * 9)
        counters[level] += 1
        for deeper in range(level + 1, len(counters)):
            counters[deeper] = 0

        if fmt == "bullet":
            return "• "
        if fmt in _DECIMAL_FORMATS:
            return ".".join(str(max(c, 1)) for c in counters[: level + 1]) + ". "
        n = counters[level]
        if fmt == "lowerLetter":
            return f"({chr(96 + min(n, 26))}) "
        if fmt == "upperLetter":
            return f"({chr(64 + min(n, 26))}) "
        if fmt in ("lowerRoman", "upperRoman"):
            roman = _to_roman(n)
            return f"({roman if fmt == 'lowerRoman' else roman.upper()}) "
        return ""


def _table_lines(table: Table) -> list[str]:
    lines = []
    for row in table.rows:
        cells: list[str] = []
        for cell in row.cells:
            text = " ".join(cell.text.split())
            if text and (not cells or cells[-1] != text):  # merged cells repeat their text
                cells.append(text)
        if cells:
            lines.append(" | ".join(cells))
    return lines


def _docx_blocks(document) -> list[str]:
    """Body paragraphs and table rows in document order. Headers, footers
    and footnotes are not read.
    """
    numberer = _ListNumberer(_numbering_formats(document))
    blocks = []
    for child in document.element.body.iterchildren():
        if child.tag == qn("w:p"):
            paragraph = Paragraph(child, document)
            text = paragraph.text.strip()
            if text:
                blocks.append(numberer.prefix(paragraph) + text)
        elif child.tag == qn("w:tbl"):
            blocks.extend(_table_lines(Table(child, document)))
    return blocks


def extract_docx(content: bytes) -> str:
    try:
        document = docx.Document(io.BytesIO(content))
        # blank line between Word paragraphs: each one is a real paragraph, not a wrapped line
        text = "\n\n".join(_docx_blocks(document)).strip()
    except ExtractionError:
        raise
    except Exception as e:
        raise ExtractionError(
            "Could not read the DOCX. The file may be damaged or unsupported."
        ) from e

    if not text:
        raise ExtractionError("DOCX has no extractable text")
    return text


def extract_text(content: bytes) -> str:
    try:
        text = content.decode("utf-8").strip()
    except UnicodeDecodeError as e:
        raise ExtractionError(
            "Could not read the text file. Please use UTF-8 encoding."
        ) from e

    if not text:
        raise ExtractionError("text file is empty")
    return text



FURNITURE_MIN_REPEATS = 3
MAX_FURNITURE_CHARS = 80
_GAP_RE = re.compile(r"[ \t]{3,}")


# content, not page furniture: ends like a sentence, or starts like a clause or list item ("4.", "(a)")
_CONTENT_LINE_RE = re.compile(r"[.;:]$|^\(?(?:\d{1,3}|[a-z]|[ivx]{1,4})[.)]", re.IGNORECASE)


def _furniture_key(text: str) -> str:
    # exact text: lines differing only in a number ("Instalment 1: ...", "Instalment 2: ...") are content;
    # page numbers have their own rule
    return " ".join(text.split()).lower()


def strip_page_furniture(text: str) -> str:
    """Removes what page layout leaves in the text: page-number lines ("2",
    "- 3 -", "Page 1 of 3"), short lines repeated on every page ("Source: ACME,
    8-K, 3/20/2020", "Confidential"), and the same debris stuck to the start or
    end of a line ("(Translation, for reference only)   1.2 Covenants ...",
    "... to ChipMOS.   - 1 -"). A part of a line is only removed when it is a
    page number or a phrase repeated as a whole line or line start elsewhere —
    never just because of a gap, which justified text is full of.
    """
    lines = text.splitlines()

    def is_candidate(unit: str) -> bool:
        unit = unit.strip()
        return (
            0 < len(unit) <= MAX_FURNITURE_CHARS
            and any(ch.isalpha() for ch in unit)
            and not _CONTENT_LINE_RE.search(unit)
        )

    whole: dict[str, int] = {}  # how often each short line appears on its own
    prefix: dict[str, int] = {}  # how often it appears as the first segment of a longer line
    for line in lines:
        segments = _GAP_RE.split(line.strip())
        if is_candidate(line.strip()):
            whole[_furniture_key(line)] = whole.get(_furniture_key(line), 0) + 1
        if len(segments) > 1 and is_candidate(segments[0]):
            prefix[_furniture_key(segments[0])] = prefix.get(_furniture_key(segments[0]), 0) + 1

    def is_repeated_phrase(unit: str) -> bool:
        # 2+ words, so a clause number ("1    PURPOSE") or a form label ("Name:  ...") never counts
        key = _furniture_key(unit)
        return len(unit.split()) >= 2 and whole.get(key, 0) + prefix.get(key, 0) >= FURNITURE_MIN_REPEATS

    def is_furniture_line(line: str) -> bool:
        line = line.strip()
        if _PAGE_NUMBER_RE.match(line):
            return True
        return is_candidate(line) and (
            whole.get(_furniture_key(line), 0) >= FURNITURE_MIN_REPEATS or is_repeated_phrase(line)
        )

    cleaned = []
    for line in lines:
        if line.strip() and is_furniture_line(line):
            cleaned.append("")
            continue
        segments = _GAP_RE.split(line.strip())
        if len(segments) > 1 and is_candidate(segments[0]) and is_repeated_phrase(segments[0]):
            segments = segments[1:]
        if len(segments) > 1 and _PAGE_NUMBER_RE.match(segments[-1].strip()):
            segments = segments[:-1]
        cleaned.append("   ".join(segments) if len(segments) < len(_GAP_RE.split(line.strip())) else line)
    return "\n".join(cleaned)


def extract(filename: str, content: bytes) -> str:
    lower = filename.lower()
    if lower.endswith(".pdf"):
        text = extract_pdf(content)
    elif lower.endswith(".docx"):
        text = extract_docx(content)
    elif lower.endswith(".txt"):
        text = extract_text(content)
    else:
        raise ExtractionError(f"unsupported file type: {filename}")
    return strip_page_furniture(text).strip()


def parse_document(filename: str, content: bytes) -> list[Clause]:
    """File bytes -> ordered clauses. The Phase 1 deliverable end-to-end."""
    return split_clauses(extract(filename, content))
