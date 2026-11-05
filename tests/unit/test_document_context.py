from app.parsing.clause_splitter import split_clauses
from app.rag.document_context import (
    MAX_CONTEXT_CHARS,
    attach_context,
    build_document_context,
    retrieve_clause_context,
)

CONTRACT = """SERVICE AGREEMENT

This Agreement is made between Acme Ltd, a company registered in Pune (the "Provider") and John Doe (the "Client").

1. Definitions
"Services" means the software development work described in Schedule A.
"Fee" shall mean INR 50,000 per month.

2. Payment
The Client shall pay the Fee within 15 days of each invoice, subject to Section 4.

3. Delivery
The Provider shall deliver the Services as described in Section 7 of the Schedule.

4. Disputes
Invoices disputed in writing within 5 days are not payable until resolved.
"""


def _by_id(clauses):
    return {c.id: c for c in clauses}


def test_parties_come_from_the_preamble():
    clauses = split_clauses(CONTRACT)
    context = build_document_context(CONTRACT, clauses)

    assert context.parties == [
        "Provider: Acme Ltd, a company registered in Pune",
        "Client: John Doe",
    ]


def test_means_style_definitions_are_indexed():
    context = build_document_context(CONTRACT, split_clauses(CONTRACT))
    assert context.definitions["Services"].startswith('"Services" means the software development work')
    assert context.definitions["Fee"] == '"Fee" shall mean INR 50,000 per month'


def test_clause_gets_only_the_definitions_it_uses():
    clauses = _by_id(attach_context(CONTRACT, split_clauses(CONTRACT)))
    assert set(clauses["clause_3"].context.definitions) == {"Fee"}
    assert set(clauses["clause_4"].context.definitions) == {"Services"}


def test_defining_clause_does_not_get_its_own_definitions_back():
    clauses = _by_id(attach_context(CONTRACT, split_clauses(CONTRACT)))
    assert clauses["clause_2"].context.definitions == {}


def test_cross_reference_retrieves_the_referenced_section():
    clauses = _by_id(attach_context(CONTRACT, split_clauses(CONTRACT)))
    referenced = clauses["clause_3"].context.referenced_sections
    assert list(referenced) == ["4"]
    assert "disputed in writing within 5 days" in referenced["4"]


def test_references_to_a_schedule_are_not_resolved_against_this_documents_sections():
    clauses = _by_id(attach_context(CONTRACT, split_clauses(CONTRACT)))
    assert clauses["clause_4"].context.referenced_sections == {}


def test_sub_clause_reference_falls_back_to_parent_clause():
    text = "1. Fees\nPay monthly.\n1.1. Late fees apply.\n2. Termination\nBreach of Section 1.3 allows termination."
    clauses = _by_id(attach_context(text, split_clauses(text)))
    assert "Pay monthly." in clauses["clause_3"].context.referenced_sections["1"]


def test_hereinafter_inline_definitions_are_recognised():
    text = (
        "This lease is between Ravi Kumar (hereinafter referred to as \"Landlord\") "
        "and Meera Shah (hereinafter \"Tenant\").\n\n1. Rent\nThe Tenant pays the Landlord monthly."
    )
    context = build_document_context(text, split_clauses(text))
    assert context.parties == ["Landlord: Ravi Kumar", "Tenant: Meera Shah"]


def test_document_without_definitions_or_references_gets_no_context():
    text = "1. Term\nThis lasts one year.\n\n2. Notice\nGive notice in writing."
    clauses = attach_context(text, split_clauses(text))
    assert all(c.context is None for c in clauses)


def test_context_is_capped_per_clause():
    definitions = "\n".join(f'"Term{i}" means a deliberately long definition {"x" * 250}.' for i in range(20))
    uses = " ".join(f"Term{i}" for i in range(20))
    text = f"1. Definitions\n{definitions}\n\n2. Use\n{uses}"
    clauses = split_clauses(text)
    result = retrieve_clause_context(clauses[1], build_document_context(text, clauses))
    total = sum(len(v) for v in result.definitions.values())
    assert 0 < total <= MAX_CONTEXT_CHARS
    assert len(result.definitions) < 20


def test_preamble_clause_does_not_get_its_own_parties_back():
    clauses = _by_id(attach_context(CONTRACT, split_clauses(CONTRACT)))
    assert clauses["clause_1"].heading == "Preamble"
    assert clauses["clause_1"].context is None or clauses["clause_1"].context.parties == []
    assert clauses["clause_3"].context.parties == ["Provider: Acme Ltd, a company registered in Pune", "Client: John Doe"]


def test_abbreviation_dots_in_party_names_are_not_sentence_breaks():
    text = (
        'This Agreement is made between Northwind Logistics Pvt. Ltd. (the "Supplier") '
        'and Dr. A. Rao (the "Consultant").\n\n1. Fees\nThe Supplier pays the Consultant monthly.'
    )
    context = build_document_context(text, split_clauses(text))

    assert context.parties == ["Supplier: Northwind Logistics Pvt. Ltd.", "Consultant: Dr. A. Rao"]


def _context_for(text: str, heading_prefix: str):
    clauses = attach_context(text, split_clauses(text))
    return next(c.context for c in clauses if (c.heading or "").startswith(heading_prefix))


def test_plural_and_possessive_uses_of_a_defined_term_get_its_definition():
    text = '1. Definitions\n"Business Day" means a weekday.\n\n2. Orders\nOrders take 5 Business Days.\n\n3. Supplier\n"Supplier" means Acme.\n\n4. Risk\nThe Supplier\'s risk ends on delivery.'
    assert "Business Day" in _context_for(text, "2.").definitions
    assert "Supplier" in _context_for(text, "4.").definitions


def test_definition_that_introduces_a_list_keeps_the_list():
    text = '1. Definitions\n"Goods" means:\n(a) rice; and\n(b) wheat.\n\n2. Delivery\nThe Goods are delivered monthly.'
    definition = _context_for(text, "2.").definitions["Goods"]
    assert "rice" in definition and "wheat" in definition


def test_single_quoted_definitions_are_found():
    text = "1. Definitions\n'Confidential Information' means all non-public information.\n\n2. Secrecy\nKeep Confidential Information secret."
    assert "Confidential Information" in _context_for(text, "2.").definitions


def test_definition_is_not_cut_at_an_abbreviation_dot():
    text = '1. Definitions\n"Premises" means flat No. 302, Sunrise Apartments.\n\n2. Use\nThe Premises are residential.'
    assert "302, Sunrise Apartments" in _context_for(text, "2.").definitions["Premises"]


def test_pointer_definition_resolves_to_the_clause_it_points_to_and_the_defining_clause_gets_nothing_back():
    text = (
        '1. Definitions\n"Term" has the meaning given to it in Clause 2.\n\n'
        '2. Duration\nThis Agreement lasts twelve (12) months (the "Term").\n\n'
        "3. Renewal\nThe Term may be renewed once."
    )
    assert "twelve (12) months" in _context_for(text, "3.").definitions["Term"]
    assert _context_for(text, "1.") is None or "Term" not in _context_for(text, "1.").definitions
    assert _context_for(text, "2.") is None or "Term" not in _context_for(text, "2.").definitions


def test_reference_lists_and_ranges_retrieve_every_section():
    text = "\n\n".join(f"{n}. Heading {n}\nBody {n}." for n in range(1, 7)) + "\n\n7. Survival\nClauses 1, 2 and 3 and Sections 4 to 6 survive."
    assert set(_context_for(text, "7.").referenced_sections) == {"1", "2", "3", "4", "5", "6"}


def test_references_into_a_schedule_are_ignored_even_as_a_range():
    text = "1. Scope\nBody.\n\n2. Pricing\nBody.\n\n3. Non-compete\nAs described in paragraphs 2 to 3 of Schedule B."
    assert _context_for(text, "3.") is None or not _context_for(text, "3.").referenced_sections


def test_second_party_entry_has_no_leading_and():
    text = 'This Agreement is made between Ravi Kumar, of Pune (the "Owner"), and Priya Shah, of Mumbai (the "Tenant").\n\n1. Rent\nThe Tenant pays the Owner.'
    context = build_document_context(text, split_clauses(text))
    assert context.parties[1] == "Tenant: Priya Shah, of Mumbai"


def test_the_document_naming_itself_is_not_a_definition():
    text = '1.1 The purpose of this distribution Agreement (hereinafter "Agreement") is to license Content.\n\n1.2 This Agreement lasts one year.'
    assert _context_for(text, "1.2") is None


def test_terms_defined_inside_a_sentence_are_found():
    text = (
        '1. Capital\nAIG keeps Total Adjusted Capital above the Specified Minimum Percentage.\n\n'
        '2. Defined Terms\nThe terms "Total Adjusted Capital" and "RBC" shall have the meanings ascribed under Texas law. '
        'The term "Specified Minimum Percentage" shall be equal to the percentage in Schedule 1.'
    )
    assert set(_context_for(text, "1.").definitions) == {"Total Adjusted Capital", "Specified Minimum Percentage"}


def test_unquoted_and_unbracketed_definitions_and_parties_are_found():
    text = (
        "CONTENT AGREEMENT\n\nbetween\n\nData Call Technologies, Inc. 600 Kenrick, Houston\n\n"
        'hereinafter referred to as "Licensor"\n\nand\n\nPLAN_B MEDIA AG Schaafenstr. 25 Cologne hereinafter referred to as "plan_b"\n\n'
        "1.1 Licensor supplies Content to End Users.\n\n1.2 End User means any person receiving Content on a mobile device."
    )
    context = build_document_context(text, split_clauses(text))
    assert context.parties[0].startswith("Licensor: Data Call Technologies, Inc.")
    assert context.parties[1].startswith("plan_b: PLAN_B MEDIA AG")
    assert "End User" in _context_for(text, "1.1").definitions


def test_two_terms_in_one_bracket_and_group_terms():
    text = (
        'This Amendment is made by and among Veoneer AB, a Swedish corporation ("Veoneer AB") and Veoneer US, Inc. '
        '("Veoneer US" and together with Veoneer AB, the "Veoneer Parties").\n\nRECITALS\n\n'
        '(A) Veoneer AB sells shares under the VNBJ Share Purchase Agreement (the "VNBJ SPA," and the completion '
        'of the sale under the VNBJ SPA, the "VNBJ Closing").\n\n'
        "Article 1. Termination\nOn the VNBJ Closing the Veoneer Parties leave the joint venture."
    )
    context = build_document_context(text, split_clauses(text))
    assert "Veoneer Parties: Veoneer US and Veoneer AB" in context.parties
    assert context.definitions["VNBJ Closing"].startswith("VNBJ Closing: the completion of the sale")
    assert "VNBJ SPA" in context.definitions


def test_recital_terms_are_definitions_not_parties():
    text = (
        'This Agreement is made between American International Group, Inc. ("AIG") and American General Life Insurance '
        'Company (the "Company").\n\nWHEREAS, the Company is regulated by the insurance laws of Texas (the "Domiciliary State");\n\n'
        "1. Approval\nContributions must be approved by the Domiciliary State."
    )
    context = build_document_context(text, split_clauses(text))
    assert [p.split(":")[0] for p in context.parties] == ["AIG", "Company"]
    assert "Domiciliary State" in _context_for(text, "1.").definitions


def test_references_into_other_documents_are_ignored_but_this_agreement_is_not():
    text = (
        "1. Contributions\nBody.\n\n2. Timing\nBody.\n\n"
        "3. Accounting\nRecognised under paragraph 1 of Statement of Accounting Principles No. 72 and Sections 2.1 of the JV Agreement.\n\n"
        "4. Rights\nPolicyholders may enforce paragraph 1 of this Agreement."
    )
    assert _context_for(text, "3.") is None
    assert set(_context_for(text, "4.").referenced_sections) == {"1"}


def test_a_term_inside_a_longer_defined_term_is_not_a_separate_use_and_apostrophes_stay_in_terms():
    text = (
        '1. Definitions\n"RBC" means risk-based capital. "Company Action Level RBC" means the RBC level set by regulators. '
        '"Moody\'s" means Moody\'s Investors Service.\n\n2. Ratings\nThe Company Action Level RBC is reviewed by Moody\'s.'
    )
    assert set(_context_for(text, "2.").definitions) == {"Company Action Level RBC", "Moody's"}


def test_with_many_parties_a_clause_only_gets_the_ones_it_names():
    names = ["Alpha", "Bravo", "Charlie", "Delta", "Echo"]
    preamble = "This Agreement is made between " + ", ".join(f'{n} Ltd ("{n}")' for n in names) + "."
    text = preamble + "\n\n1. Payment\nAlpha pays Bravo monthly."
    assert [p.split(":")[0] for p in _context_for(text, "1.").parties] == ["Alpha", "Bravo"]
