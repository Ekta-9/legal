import json

import pytest

from app.llm.simplify import build_prompt, parse_batch_response, simplify_clauses
from app.models.schemas import Clause

CLAUSES = [
    Clause(id="clause_1", heading="1. Definitions", text="Party means either signatory."),
    Clause(id="clause_2", heading="2. Term", text="This lasts one year."),
]


def test_build_prompt_includes_every_clause_id_and_text():
    prompt = build_prompt(CLAUSES)
    assert "clause_1" in prompt
    assert "clause_2" in prompt
    assert "Party means either signatory." in prompt
    assert "This lasts one year." in prompt


def test_parse_valid_response_returns_all_clauses_none_dropped():
    raw = json.dumps(
        {
            "results": [
                {"clause_id": "clause_1", "simplified": "A party is a signer.", "self_check": False},
                {"clause_id": "clause_2", "simplified": "One year long.", "self_check": True},
            ]
        }
    )
    simplified, dropped = parse_batch_response(raw, CLAUSES)
    assert dropped == []
    assert len(simplified) == 2
    by_id = {s.id: s for s in simplified}
    assert by_id["clause_1"].simplified == "A party is a signer."
    assert by_id["clause_1"].self_check is False
    assert by_id["clause_2"].self_check is True
    assert by_id["clause_2"].original == "This lasts one year."


def test_parse_malformed_json_drops_whole_batch_without_raising():
    simplified, dropped = parse_batch_response("not json at all {{{", CLAUSES)
    assert simplified == []
    assert set(dropped) == {"clause_1", "clause_2"}


def test_parse_missing_results_key_drops_whole_batch():
    simplified, dropped = parse_batch_response(json.dumps({"oops": []}), CLAUSES)
    assert simplified == []
    assert set(dropped) == {"clause_1", "clause_2"}


def test_parse_partial_batch_keeps_present_drops_missing():
    raw = json.dumps(
        {"results": [{"clause_id": "clause_1", "simplified": "A party is a signer.", "self_check": False}]}
    )
    simplified, dropped = parse_batch_response(raw, CLAUSES)
    assert [s.id for s in simplified] == ["clause_1"]
    assert dropped == ["clause_2"]


def test_parse_silently_dropped_clause_in_model_output():
    # model returned a result for an id that was never in the batch — ignored, not crashed
    raw = json.dumps(
        {
            "results": [
                {"clause_id": "clause_1", "simplified": "A party is a signer.", "self_check": False},
                {"clause_id": "clause_99", "simplified": "Hallucinated clause.", "self_check": False},
            ]
        }
    )
    simplified, dropped = parse_batch_response(raw, CLAUSES)
    assert [s.id for s in simplified] == ["clause_1"]
    assert dropped == ["clause_2"]


def test_parse_entry_with_blank_simplified_text_is_dropped():
    raw = json.dumps(
        {
            "results": [
                {"clause_id": "clause_1", "simplified": "   ", "self_check": False},
                {"clause_id": "clause_2", "simplified": "One year long.", "self_check": False},
            ]
        }
    )
    simplified, dropped = parse_batch_response(raw, CLAUSES)
    assert [s.id for s in simplified] == ["clause_2"]
    assert dropped == ["clause_1"]


@pytest.mark.asyncio
async def test_simplify_clauses_end_to_end_with_fake_client(fake_groq):
    simplified, dropped = await simplify_clauses(CLAUSES, fake_groq)
    assert dropped == []
    assert len(simplified) == 2
    assert all(s.simplified.startswith("SIMPLIFIED:") for s in simplified)


@pytest.mark.asyncio
async def test_simplify_clauses_batches_across_multiple_calls(fake_groq):
    many_clauses = [Clause(id=f"clause_{i}", text=f"Text {i}") for i in range(1, 15)]
    simplified, dropped = await simplify_clauses(many_clauses, fake_groq, batch_size=6)
    assert dropped == []
    assert len(simplified) == 14
    assert len(fake_groq.prompts) == 3  # ceil(14 / 6)


@pytest.mark.asyncio
async def test_cache_hit_never_calls_client(fake_groq, tmp_path):
    from app.cache.store import CacheStore

    cache = CacheStore(tmp_path / "cache.sqlite3")
    cache.put(CLAUSES[0].text, "Cached simplification.", self_check=True)

    simplified, dropped = await simplify_clauses(CLAUSES, fake_groq, cache=cache)

    assert dropped == []
    by_id = {s.id: s for s in simplified}
    assert by_id["clause_1"].simplified == "Cached simplification."
    assert by_id["clause_1"].self_check is True
    assert by_id["clause_2"].simplified.startswith("SIMPLIFIED:")
    # only clause_2 (the cache miss) should have gone to the LLM
    assert len(fake_groq.prompts) == 1
    assert "clause_2" in fake_groq.prompts[0]
    assert "clause_1" not in fake_groq.prompts[0]


@pytest.mark.asyncio
async def test_cache_miss_writes_through_after_llm_call(fake_groq, tmp_path):
    from app.cache.store import CacheStore

    cache = CacheStore(tmp_path / "cache.sqlite3")
    assert cache.get(CLAUSES[0].text) is None

    await simplify_clauses(CLAUSES, fake_groq, cache=cache)

    hit = cache.get(CLAUSES[0].text)
    assert hit is not None
    assert hit["simplified"].startswith("SIMPLIFIED:")


@pytest.mark.asyncio
async def test_second_run_with_full_cache_makes_zero_llm_calls(fake_groq, tmp_path):
    from app.cache.store import CacheStore

    cache = CacheStore(tmp_path / "cache.sqlite3")
    await simplify_clauses(CLAUSES, fake_groq, cache=cache)
    assert len(fake_groq.prompts) == 1  # first run: one batch call

    simplified, dropped = await simplify_clauses(CLAUSES, fake_groq, cache=cache)

    assert dropped == []
    assert len(simplified) == 2
    assert len(fake_groq.prompts) == 1  # unchanged — second run made no new calls


@pytest.mark.asyncio
async def test_verify_fn_runs_per_batch_and_result_reflects_its_output(fake_groq):
    calls = []

    async def verify_fn(simplified, batch):
        calls.append((simplified, batch))
        return [s.model_copy(update={"simplified": "VERIFIED", "self_check": False}) for s in simplified]

    simplified, dropped = await simplify_clauses(CLAUSES, fake_groq, verify_fn=verify_fn)

    assert dropped == []
    assert len(calls) == 1  # one call per batch (single batch here)
    assert all(s.simplified == "VERIFIED" for s in simplified)


@pytest.mark.asyncio
async def test_verify_fn_output_is_what_gets_cached(fake_groq, tmp_path):
    from app.cache.store import CacheStore

    cache = CacheStore(tmp_path / "cache.sqlite3")

    async def verify_fn(simplified, batch):
        return [s.model_copy(update={"simplified": "VERIFIED", "self_check": False}) for s in simplified]

    await simplify_clauses(CLAUSES, fake_groq, cache=cache, verify_fn=verify_fn)

    hit = cache.get(CLAUSES[0].text)
    assert hit["simplified"] == "VERIFIED"  # post-verify text, not the raw LLM output
