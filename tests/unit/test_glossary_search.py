import json

import pytest

from app.rag.glossary_store import GlossaryStore

TEST_GLOSSARY = [
    {
        "term": "Indemnification",
        "definition": "A promise by one party to cover the other party's losses, damages, or legal costs.",
    },
    {
        "term": "Force Majeure",
        "definition": "A clause excusing performance when extraordinary events like natural disasters make it impossible.",
    },
    {
        "term": "Arbitration",
        "definition": "A private process for resolving disputes outside of court using a neutral arbitrator.",
    },
    {
        "term": "Confidentiality",
        "definition": "An obligation to keep certain information secret and not share it with outside parties.",
    },
    {
        "term": "Termination",
        "definition": "The act of ending a contract before its natural conclusion.",
    },
]


@pytest.fixture(scope="module")
def store(tmp_path_factory):
    path = tmp_path_factory.mktemp("glossary") / "glossary.json"
    path.write_text(json.dumps(TEST_GLOSSARY), encoding="utf-8")
    return GlossaryStore(path)


def test_search_returns_correct_top_match_for_clear_query(store):
    results = store.search("The party shall indemnify and hold harmless the other party from any claims.")
    assert len(results) > 0
    assert results[0]["term"] == "Indemnification"


def test_search_matches_arbitration_over_unrelated_terms(store):
    results = store.search("Any dispute shall be resolved through binding arbitration rather than in court.")
    assert results[0]["term"] == "Arbitration"


def test_top_k_limits_result_count(store):
    results = store.search(
        "The party shall indemnify and hold harmless the other party from any claims.", top_k=1
    )
    assert len(results) <= 1


def test_threshold_filters_out_low_relevance_matches(store):
    results = store.search(
        "The party shall indemnify and hold harmless the other party from any claims.", threshold=0.99
    )
    assert results == []


def test_empty_query_returns_empty_list(store):
    assert store.search("") == []
    assert store.search("   ") == []


def test_unrelated_text_returns_no_high_confidence_match(store):
    results = store.search("The weather today is sunny with a light breeze over the lake.")
    assert results == []


def test_results_sorted_by_score_descending(store):
    results = store.search("The party shall indemnify and hold harmless the other party from any claims.")
    scores = [r["score"] for r in results]
    assert scores == sorted(scores, reverse=True)


def test_empty_glossary_file_returns_no_matches(tmp_path):
    path = tmp_path / "empty_glossary.json"
    path.write_text("[]", encoding="utf-8")
    empty_store = GlossaryStore(path)
    assert empty_store.search("indemnify and hold harmless") == []
