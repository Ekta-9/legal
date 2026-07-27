"""Regenerates the binary test fixtures (PDF/DOCX) from scratch.

Run with: python tests/fixtures/generate_fixtures.py
The fixtures are committed to the repo, so this only needs to run again if
the fixture content itself needs to change.
"""

from pathlib import Path

import docx
import fitz

FIXTURES_DIR = Path(__file__).resolve().parent

CLEAN_CLAUSES = [
    (
        "1. Definitions",
        [
            'In this agreement, "Party" means either signatory to this contract.',
            '"Effective Date" means the date both parties sign below.',
        ],
    ),
    (
        "2. Term",
        [
            "This agreement begins on the Effective Date and continues for one year",
            "unless terminated earlier under Section 3.",
        ],
    ),
    (
        "3. Termination",
        [
            "Either party may terminate this agreement with 30 days written notice",
            "delivered to the other party's address of record.",
        ],
    ),
]


def build_sample_clean_pdf() -> None:
    doc = fitz.open()
    page = doc.new_page()
    y = 72
    for heading, body_lines in CLEAN_CLAUSES:
        page.insert_text((72, y), heading, fontsize=12)
        y += 18
        for line in body_lines:
            page.insert_text((72, y), line, fontsize=11)
            y += 16
        y += 12
    doc.save(FIXTURES_DIR / "sample_clean.pdf")
    doc.close()


def build_sample_multicolumn_pdf() -> None:
    """Two side-by-side columns, each a self-contained multi-line clause.

    Extraction must read each column top-to-bottom in full before moving to
    the next column — naive row-by-row extraction across the full page
    width would interleave the two clauses' lines and corrupt both.
    """
    doc = fitz.open()
    page = doc.new_page()

    left_lines = [
        "1. Confidentiality",
        "Each party agrees to keep the other party's proprietary",
        "information secret and to use it only for this agreement's",
        "purposes, for a period of five years after disclosure.",
    ]
    right_lines = [
        "2. Governing Law",
        "This agreement is governed by the laws of the state in",
        "which the receiving party maintains its principal place",
        "of business, without regard to conflict-of-law rules.",
    ]

    y = 72
    for line in left_lines:
        page.insert_text((72, y), line, fontsize=11)
        y += 16

    y = 72
    for line in right_lines:
        page.insert_text((320, y), line, fontsize=11)
        y += 16

    doc.save(FIXTURES_DIR / "sample_multicolumn.pdf")
    doc.close()


def build_sample_scanned_pdf() -> None:
    """A page with an image only — no text layer at all."""
    doc = fitz.open()
    page = doc.new_page()
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 200, 200))
    pix.set_rect(pix.irect, (255, 255, 255))
    page.insert_image(fitz.Rect(72, 72, 272, 272), pixmap=pix)
    doc.save(FIXTURES_DIR / "sample_scanned.pdf")
    doc.close()


def build_sample_docx() -> None:
    document = docx.Document()
    for heading, body_lines in CLEAN_CLAUSES:
        document.add_paragraph(heading)
        for line in body_lines:
            document.add_paragraph(line)
        document.add_paragraph("")
    document.save(FIXTURES_DIR / "sample.docx")


if __name__ == "__main__":
    build_sample_clean_pdf()
    build_sample_multicolumn_pdf()
    build_sample_scanned_pdf()
    build_sample_docx()
    print(f"Fixtures written to {FIXTURES_DIR}")
