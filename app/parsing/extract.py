import io

import docx
import fitz  # PyMuPDF
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph

from app.models.schemas import Clause
from app.parsing.clause_splitter import split_clauses


class ExtractionError(Exception):
    """Raised when a document cannot be parsed into usable text."""


class NoTextLayerError(ExtractionError):
    """Raised for PDFs with no extractable text layer (e.g. scanned pages)."""



def extract_pdf(content: bytes) -> str:
    try:
        doc = fitz.open(stream=content, filetype="pdf")
        try:
            pages = []
            for page in doc:
                blocks = [
                    b for b in page.get_text("blocks")
                    if b[6] == 0 and b[4].strip()
                ]
                if not blocks:
                    continue

                mid_x = page.rect.width / 2

                def column(block):
                    return 0 if block[0] < mid_x else 1

                blocks.sort(key=lambda b: (column(b), round(b[1], 1)))
                pages.append("\n\n".join(b[4].strip() for b in blocks))
        finally:
            doc.close()

    except ExtractionError:
        raise
    except Exception as e:
        raise ExtractionError(
            "Could not read the PDF. The file may be damaged or unsupported."
        ) from e

    text = "\n\n".join(pages).strip()
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



def extract(filename: str, content: bytes) -> str:
    lower = filename.lower()
    if lower.endswith(".pdf"):
        return extract_pdf(content)
    if lower.endswith(".docx"):
        return extract_docx(content)
    if lower.endswith(".txt"):
        return extract_text(content)
    raise ExtractionError(f"unsupported file type: {filename}")


def parse_document(filename: str, content: bytes) -> list[Clause]:
    """File bytes -> ordered clauses. The Phase 1 deliverable end-to-end."""
    return split_clauses(extract(filename, content))
