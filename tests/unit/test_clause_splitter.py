from app.parsing.clause_splitter import split_clauses

NUMBERED_TEXT = """1. Definitions
In this agreement, "Party" means either signatory.

2. Term
This agreement begins on the effective date and continues for one year.

3. Termination
Either party may terminate with 30 days written notice.
"""

SECTION_TEXT = """SECTION 1: Scope
This section describes the scope of work.

SECTION 2: Payment
Payment is due within 30 days of invoice.
"""

UNNUMBERED_TEXT = """This is the first paragraph with no numbering at all.

This is the second paragraph, also unnumbered.

This is the third and final paragraph.
"""


def test_numbered_clauses_split_on_each_number():
    clauses = split_clauses(NUMBERED_TEXT)
    assert [c.id for c in clauses] == ["clause_1", "clause_2", "clause_3"]
    assert clauses[0].heading == "1. Definitions"
    assert "Party" in clauses[0].text
    assert clauses[1].heading == "2. Term"
    assert clauses[2].heading == "3. Termination"


def test_section_headings_are_boundaries():
    clauses = split_clauses(SECTION_TEXT)
    assert len(clauses) == 2
    assert clauses[0].heading == "SECTION 1: Scope"
    assert clauses[1].heading == "SECTION 2: Payment"


def test_unnumbered_text_falls_back_to_blank_line_paragraphs():
    clauses = split_clauses(UNNUMBERED_TEXT)
    assert len(clauses) == 3
    assert all(c.heading is None for c in clauses)
    assert clauses[0].text.startswith("This is the first paragraph")


def test_empty_text_yields_no_clauses():
    assert split_clauses("") == []
    assert split_clauses("   \n\n  ") == []


def test_clause_ids_are_sequential_and_stable():
    clauses = split_clauses(NUMBERED_TEXT)
    ids = [c.id for c in clauses]
    assert ids == sorted(ids, key=lambda i: int(i.split("_")[1]))
