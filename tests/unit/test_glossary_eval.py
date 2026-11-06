from app.rag.glossary_store import GlossaryStore
from tests.eval.glossary_eval import score


def test_glossary_matching_does_not_regress():
    """tests/eval/glossary_eval.py on hand-labelled clauses. dev is the set the
    patterns were written against; heldout's three remaining errors are the
    "notices" (documents) and "official communication" (notice in concept only)
    cases noted in glossary_gold.json."""
    store = GlossaryStore()
    dev = score(store.search, "dev")
    heldout = score(store.search, "heldout")

    assert dev["problems"] == []
    assert heldout["precision"] >= 0.94 and heldout["recall"] >= 0.97
