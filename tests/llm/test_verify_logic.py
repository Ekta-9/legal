import json

import pytest

from app.llm.verify import make_verifier, retry_flagged_clauses
from app.models.schemas import Clause, SimplifiedClause

CLAUSES = [
    Clause(id="clause_1", text="First clause text."),
    Clause(id="clause_2", text="Second clause text."),
]


class ScriptedClient:
    """Returns each response in `responses` in order, one per `complete` call."""

    def __init__(self, responses: list[str]):
        self.responses = responses
        self.calls: list[str] = []

    async def complete(self, prompt: str) -> str:
        self.calls.append(prompt)
        return self.responses[len(self.calls) - 1]


def _response(entries: list[dict]) -> str:
    return json.dumps({"results": entries})


@pytest.mark.asyncio
async def test_no_flagged_clauses_means_no_retry_call():
    simplified = [
        SimplifiedClause(id="clause_1", original="x", simplified="y", self_check=False),
        SimplifiedClause(id="clause_2", original="x", simplified="y", self_check=False),
    ]
    client = ScriptedClient([])

    result = await retry_flagged_clauses(simplified, CLAUSES, client)

    assert result == simplified
    assert client.calls == []


@pytest.mark.asyncio
async def test_flagged_clause_retried_and_clears_flag_on_success():
    simplified = [
        SimplifiedClause(id="clause_1", original="x", simplified="risky version", self_check=True),
        SimplifiedClause(id="clause_2", original="x", simplified="fine version", self_check=False),
    ]
    client = ScriptedClient(
        [_response([{"clause_id": "clause_1", "simplified": "confident retry", "self_check": False}])]
    )

    result = await retry_flagged_clauses(simplified, CLAUSES, client)

    by_id = {s.id: s for s in result}
    assert by_id["clause_1"].simplified == "confident retry"
    assert by_id["clause_1"].self_check is False
    assert by_id["clause_2"].simplified == "fine version"  # untouched, never retried
    assert len(client.calls) == 1
    # only the flagged clause is included in the retry batch
    assert "clause_1" in client.calls[0]
    assert "clause_2" not in client.calls[0]


@pytest.mark.asyncio
async def test_still_flagged_after_retry_keeps_badge_never_suppressed():
    simplified = [
        SimplifiedClause(id="clause_1", original="x", simplified="risky version", self_check=True),
    ]
    client = ScriptedClient(
        [_response([{"clause_id": "clause_1", "simplified": "still risky", "self_check": True}])]
    )

    result = await retry_flagged_clauses(simplified, CLAUSES, client)

    assert len(result) == 1  # never suppressed/dropped
    assert result[0].self_check is True
    assert result[0].simplified == "still risky"


@pytest.mark.asyncio
async def test_retry_never_loops_exactly_one_call_even_if_still_flagged():
    simplified = [
        SimplifiedClause(id="clause_1", original="x", simplified="risky", self_check=True),
    ]
    # even though the retry itself came back flagged, only one retry call is ever made
    client = ScriptedClient(
        [_response([{"clause_id": "clause_1", "simplified": "still risky", "self_check": True}])]
    )

    await retry_flagged_clauses(simplified, CLAUSES, client)

    assert len(client.calls) == 1


@pytest.mark.asyncio
async def test_malformed_retry_response_keeps_original_flagged_result():
    simplified = [
        SimplifiedClause(id="clause_1", original="x", simplified="risky version", self_check=True),
    ]
    client = ScriptedClient(["not valid json {{{"])

    result = await retry_flagged_clauses(simplified, CLAUSES, client)

    assert len(result) == 1  # never suppressed even though the retry parse failed
    assert result[0].simplified == "risky version"
    assert result[0].self_check is True


@pytest.mark.asyncio
async def test_make_verifier_binds_client_and_matches_verify_fn_signature():
    simplified = [
        SimplifiedClause(id="clause_1", original="x", simplified="risky", self_check=True),
    ]
    client = ScriptedClient(
        [_response([{"clause_id": "clause_1", "simplified": "fixed", "self_check": False}])]
    )
    verify_fn = make_verifier(client)

    result = await verify_fn(simplified, CLAUSES)

    assert result[0].simplified == "fixed"
    assert result[0].self_check is False
