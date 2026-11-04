import json
from pathlib import Path

import pytest

from app.parsing.extract import (
    ExtractionError,
    NoTextLayerError,
    extract,
    parse_document,
)

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"
GOLDEN = json.loads((FIXTURES_DIR / "golden_clauses.json").read_text())


def _read_fixture(name: str) -> bytes:
    return (FIXTURES_DIR / name).read_bytes()


@pytest.mark.parametrize("filename", ["sample_clean.pdf", "sample_multicolumn.pdf", "sample.docx"])
def test_extract_matches_golden_clause_count(filename):
    clauses = parse_document(filename, _read_fixture(filename))
    golden = GOLDEN[filename]
    assert len(clauses) == golden["clause_count"]
    assert [c.id for c in clauses] == golden["ids"]
    assert [c.heading for c in clauses] == golden["headings"]


def test_multicolumn_does_not_interleave_columns():
    clauses = parse_document("sample_multicolumn.pdf", _read_fixture("sample_multicolumn.pdf"))
    left_clause, right_clause = clauses

    # each column's clause must read as a single contiguous block —
    # naive row-by-row extraction would splice lines from the other column in
    assert "Confidentiality" in left_clause.text
    assert "Governing Law" in right_clause.text
    assert "Governing Law" not in left_clause.text
    assert "Confidentiality" not in right_clause.text
    assert "proprietary" in left_clause.text
    assert "conflict-of-law" in right_clause.text


def test_scanned_pdf_raises_clean_error_not_crash():
    with pytest.raises(NoTextLayerError):
        extract("sample_scanned.pdf", _read_fixture("sample_scanned.pdf"))


def test_unsupported_extension_raises():
    with pytest.raises(ExtractionError):
        extract("sample.xyz", b"whatever")


def test_text_passthrough():
    clauses = parse_document("pasted.txt", b"1. First clause.\n\n2. Second clause.")
    assert len(clauses) == 2


def _docx_bytes(build) -> bytes:
    import io

    import docx

    document = docx.Document()
    build(document)
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def test_docx_auto_numbered_clauses_are_split_and_tables_are_read():
    def build(d):
        d.add_paragraph("EMPLOYMENT AGREEMENT")
        d.add_paragraph("Salary: paid monthly.", style="List Number")
        table = d.add_table(rows=1, cols=2)
        table.cell(0, 0).text = "Annual salary"
        table.cell(0, 1).text = "INR 12,00,000"
        d.add_paragraph("Termination: 60 days notice.", style="List Number")

    clauses = parse_document("contract.docx", _docx_bytes(build))

    assert [c.heading for c in clauses] == ["Preamble", "1. Salary: paid monthly.", "2. Termination: 60 days notice."]
    assert "Annual salary | INR 12,00,000" in clauses[1].text


def test_docx_bullets_are_not_numbered():
    def build(d):
        d.add_paragraph("Duties", style="List Bullet")
        d.add_paragraph("More duties", style="List Bullet")

    text = extract("x.docx", _docx_bytes(build))
    assert text == "• Duties\n\n• More duties"
