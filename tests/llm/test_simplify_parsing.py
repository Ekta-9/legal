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
