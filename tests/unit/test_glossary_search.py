import pytest

from app.rag.glossary_store import GlossaryStore


@pytest.fixture(scope="module")
def store():
    return GlossaryStore()


def _terms(store, text):
    return [m["term"] for m in store.search(text)]


def test_word_family_matches(store):
    assert _terms(store, "The Tenant shall indemnify the Owner against any loss.") == ["Indemnification"]


def test_terms_that_only_sound_related_are_not_shown(store):
    # the old embedding search showed "Statute of Limitations" and "Remedy" for a payment clause
    assert _terms(store, "The Customer shall pay each undisputed invoice within 45 days of receipt.") == []


def test_concepts_are_matched_within_one_sentence(store):
    convenience = "Either party may terminate this licence by giving one month's written notice."
    cause = "The Owner may terminate this licence forthwith if the fee remains unpaid for two months."
    assert set(_terms(store, convenience)) == {"Termination for Convenience", "Notice"}
    assert _terms(store, cause) == ["Termination for Cause"]
    # "terminate" and "breach" in different sentences is not termination for cause
    assert "Termination for Cause" not in _terms(store, "Either party may terminate this. A breach is costly.")


def test_specific_term_hides_the_general_one(store):
    terms = _terms(store, "Either party may terminate if the other commits a material breach of this Agreement.")
    assert "Material Breach" in terms
    assert "Breach of Contract" not in terms


def test_known_false_friends_are_not_matched(store):
    text = (
        "The Trust is registered under the Investment Company Act of 1940, as amended. "
        "Domini is a limited liability company. Exhibit h(2)."
    )
    assert _terms(store, text) == []


def test_terms_come_in_the_order_the_clause_raises_them_and_are_capped(store):
    text = (
        "Notwithstanding anything else, liability shall not exceed the fees, except for indemnity, wilful misconduct, "
        "negligence, tort claims or breach of this Agreement."
    )
    terms = _terms(store, text)
    assert terms[0] == "Liability"
    assert len(terms) <= 5
