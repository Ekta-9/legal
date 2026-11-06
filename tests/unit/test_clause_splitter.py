import pytest

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


def _lines(text):
    return [line.strip() for line in text.splitlines() if line.strip()]


COVERAGE_CASES = {
    "numbered": NUMBERED_TEXT,
    "sections": SECTION_TEXT,
    "unnumbered": UNNUMBERED_TEXT,
    "preamble": 'RENT AGREEMENT\nThis is between A (the "Owner") and B (the "Tenant").\n\n1. Rent\nPay monthly.\n2. Term\nOne year.',
    "wrapped": "1. Term\nThis starts on 1 January\n2025. It lasts one year.\n2. Liability\nAs set out in\nSection 7 of the Schedule, except for fraud.",
    "nested list": "1. Duties\nThe Tenant shall:\n1. pay rent;\n2. keep the flat clean.\n2. Term\nOne year.",
    "sub-clauses": "1. Definitions\n1.1 Agreement means this document.\n1.2 Services means the work.\n2. Payment\nPay on time.",
    "caps headings": "CONFIDENTIALITY\nKeep it secret.\nTERMINATION\nEither party may end this.",
    "one per line": "The Tenant pays rent.\nThe Owner fixes the roof.\nEither party may end this.",
}


@pytest.mark.parametrize("name", COVERAGE_CASES)
def test_every_line_lands_in_exactly_one_clause_in_order(name):
    """Coverage invariant: splitting never drops, duplicates or reorders text
    (it may split a line where a clause number sits mid-line)."""
    text = COVERAGE_CASES[name]
    clauses = split_clauses(text)
    assert " ".join(c.text for c in clauses).split() == text.split()
    assert [c.id for c in clauses] == [f"clause_{i}" for i in range(1, len(clauses) + 1)]


def test_text_before_the_first_clause_is_kept_as_a_preamble():
    clauses = split_clauses(COVERAGE_CASES["preamble"])
    assert clauses[0].heading == "Preamble"
    assert '(the "Owner")' in clauses[0].text
    assert [c.heading for c in clauses[1:]] == ["1. Rent", "2. Term"]


def test_wrapped_year_and_schedule_reference_do_not_start_clauses():
    clauses = split_clauses(COVERAGE_CASES["wrapped"])
    assert [c.heading for c in clauses] == ["1. Term", "2. Liability"]
    assert "except for fraud" in clauses[1].text


def test_list_nested_inside_a_clause_does_not_restart_numbering():
    clauses = split_clauses(COVERAGE_CASES["nested list"])
    assert [c.heading for c in clauses] == ["1. Duties", "2. Term"]
    assert "2. keep the flat clean." in clauses[0].text


def test_sub_clauses_without_trailing_dot_are_boundaries():
    clauses = split_clauses(COVERAGE_CASES["sub-clauses"])
    assert [c.heading for c in clauses] == [
        "1. Definitions",
        "1.1 Agreement means this document.",
        "1.2 Services means the work.",
        "2. Payment",
    ]


def test_sub_number_followed_by_lowercase_is_a_wrapped_line_not_a_boundary():
    clauses = split_clauses("1. Fees\nLate fees apply as per clause\n1.2 hereof and are payable.\n2. Term\nOne year.")
    assert [c.heading for c in clauses] == ["1. Fees", "2. Term"]


def test_unnumbered_caps_headings_are_boundaries():
    clauses = split_clauses(COVERAGE_CASES["caps headings"])
    assert [c.heading for c in clauses] == ["CONFIDENTIALITY", "TERMINATION"]


def test_one_paragraph_per_line_text_splits_per_line():
    assert len(split_clauses(COVERAGE_CASES["one per line"])) == 3


def test_hard_wrapped_prose_is_not_split_per_line():
    text = "The Tenant shall pay the rent on or before the seventh day of\neach calendar month by bank transfer to the account notified\nby the Owner in writing."
    assert len(split_clauses(text)) == 1


def _labels(text: str) -> list[str]:
    from tests.eval.rag_eval import clause_label

    return [str(clause_label(c.heading)) for c in split_clauses(text)]


def test_bare_number_before_a_caps_heading_is_a_clause_but_before_prose_is_not():
    text = "1    PURPOSE  OF  THE  AGREEMENT\n\n1.1  The purpose is set out here.\n\n15 days notice is required.\n\n2    PAYMENT\n\n2.1  Pay monthly."
    assert _labels(text) == ["1", "1.1", "2", "2.1"]


def test_lowercase_sub_clause_is_accepted_only_as_the_exact_next_number():
    text = (
        "3    OBLIGATIONS  OF  PLAN_B\n\n3.1  plan_b will distribute Content.\n\n3.2  plan_b shall market it.\n\n"
        "4.    Price\nThe price is set out in clause\n4.2 hereof and may change."
    )
    assert _labels(text) == ["3", "3.1", "3.2", "4"]


def test_heading_after_page_debris_on_the_same_line_starts_a_clause():
    text = "1.1 Scope The parties cooperate.\n\n(Translation, for reference only)   1.2 Covenants of Parties\nEach party covenants.\n\nConfidential   Article 2 Term\n2.1 Term Three years."
    clauses = split_clauses(text)
    assert _labels(text) == ["1.1", "1.2", "2", "2.1"]
    assert clauses[0].text.endswith("(Translation, for reference only)")


def test_run_on_paragraph_is_split_at_the_next_number_in_sequence_only():
    text = (
        "Agreement made this day between Principal and Distributor, who agree as follows. CONDITIONS: "
        "1. The Principal appoints the Distributor for the Territory and its customers. "
        "2. The Distributor sells in the Territory under clause 7. The rest applies. "
        "3. This Agreement lasts until March 18. 2021, unless ended earlier. 5. Nothing here is out of sequence."
    )
    assert _labels(text) == ["Preamble", "1", "2", "3"]
    assert "March 18. 2021" in split_clauses(text)[3].text


@pytest.mark.parametrize(
    "name, expected",
    [
        ("cuad_content_license", ["Preamble"] + [x for n, subs in [(1, 2), (2, 3), (3, 4), (4, 2), (5, 4), (6, 3), (7, 5), (8, 4), (9, 1), (10, 2)] for x in [str(n)] + [f"{n}.{s}" for s in range(1, subs + 1)]]),
        ("cuad_distributor", ["Preamble"] + [str(n) for n in range(1, 19)]),
        ("cuad_strategic_alliance", ["Preamble", "1", "1.1", "1.2", "1.3", "2", "2.1", "2.2", "2.3", "3"] + [f"3.{n}" for n in range(1, 13)]),
    ],
)
def test_real_contracts_split_along_their_own_numbering(name, expected):
    """CUAD contracts (tests/eval/rag_gold.json): headings without dots, lowercase
    sub-clauses, page debris before headings, and clauses run together in paragraphs."""
    from tests.eval.rag_eval import load_documents

    text = next(d["text"] for d in load_documents() if d["name"] == name)
    assert _labels(text) == expected
    assert " ".join(c.text for c in split_clauses(text)).split() == text.split()


@pytest.mark.parametrize(
    "text, expected",
    [
        ("4    REVENUES", True),
        ("Article 2 Term of Agreement", True),
        ("14. Counterparts", True),
        ("1. DEFINITIONS AND INTERPRETATION", True),
        ("5. Rent is due monthly", False),
        ("4.4 All Fees are exclusive of GST.", False),
        ("1. Rent\nPay monthly.", False),
    ],
)
def test_heading_only(text, expected):
    from app.parsing.clause_splitter import is_heading_only

    assert is_heading_only(text) is expected
