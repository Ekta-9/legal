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
