import pytest

from app.cache.store import CacheStore, clause_hash


@pytest.fixture
def store(tmp_path):
    return CacheStore(tmp_path / "cache.sqlite3")


def test_miss_on_empty_cache(store):
    assert store.get("Some clause text.") is None


def test_put_then_get_is_a_hit(store):
    store.put("Some clause text.", "Simple version.", self_check=False, heading="1. Heading")
    hit = store.get("Some clause text.")
    assert hit == {"simplified": "Simple version.", "self_check": False, "heading": "1. Heading"}


def test_hash_stable_across_whitespace_differences():
    assert clause_hash("Some   clause\ntext.") == clause_hash("Some clause text.")
    assert clause_hash("  Some clause text.  ") == clause_hash("Some clause text.")


def test_hash_differs_for_different_text():
    assert clause_hash("Clause A.") != clause_hash("Clause B.")


def test_cache_hit_ignores_whitespace_differences(store):
    store.put("Some clause text.", "Simple version.", self_check=False)
    hit = store.get("Some   clause\ntext.")
    assert hit is not None
    assert hit["simplified"] == "Simple version."


def test_different_text_is_a_miss(store):
    store.put("Clause A text.", "Simple A.", self_check=False)
    assert store.get("Clause B text.") is None


def test_prompt_version_change_invalidates_cache(store):
    store.put("Some clause.", "Simple v1.", self_check=False, prompt_version="v1")
    assert store.get("Some clause.", prompt_version="v1") is not None
    assert store.get("Some clause.", prompt_version="v2") is None


def test_put_overwrites_existing_entry(store):
    store.put("Some clause.", "First version.", self_check=False)
    store.put("Some clause.", "Second version.", self_check=True)
    hit = store.get("Some clause.")
    assert hit["simplified"] == "Second version."
    assert hit["self_check"] is True


def test_store_persists_across_instances_on_same_path(tmp_path):
    db_path = tmp_path / "shared.sqlite3"
    CacheStore(db_path).put("Persisted clause.", "Simplified.", self_check=False)
    reopened = CacheStore(db_path)
    assert reopened.get("Persisted clause.") is not None
