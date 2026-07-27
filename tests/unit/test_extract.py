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
