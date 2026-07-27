import io

import docx
import fitz  # PyMuPDF

from app.models.schemas import Clause
from app.parsing.clause_splitter import split_clauses


class ExtractionError(Exception):
    """Raised when a document cannot be parsed into usable text."""


class NoTextLayerError(ExtractionError):
    """Raised for PDFs with no extractable text layer (e.g. scanned pages)."""


def extract_pdf(content: bytes) -> str:
    doc = fitz.open(stream=content, filetype="pdf")
    try:
        pages = []
        for page in doc:
            blocks = [b for b in page.get_text("blocks") if b[6] == 0 and b[4].strip()]
            if not blocks:
                continue
            mid_x = page.rect.width / 2

            def column(block):
                return 0 if block[0] < mid_x else 1

            blocks.sort(key=lambda b: (column(b), round(b[1], 1)))
            pages.append("\n".join(b[4].strip() for b in blocks))
    finally:
        doc.close()

    text = "\n\n".join(pages).strip()
    if not text:
        raise NoTextLayerError(
            "PDF has no extractable text layer (likely a scanned document); OCR is out of scope for MVP"
        )
    return text


def extract_docx(content: bytes) -> str:
    document = docx.Document(io.BytesIO(content))
    text = "\n".join(p.text for p in document.paragraphs).strip()
    if not text:
        raise ExtractionError("DOCX has no extractable text")
    return text


def extract_text(content: bytes) -> str:
    text = content.decode("utf-8").strip()
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
