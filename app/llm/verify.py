from app.llm.simplify import CompletesPrompts, build_prompt, parse_batch_response
from app.models.schemas import Clause, SimplifiedClause


async def retry_flagged_clauses(
    simplified: list[SimplifiedClause],
    batch: list[Clause],
    client: CompletesPrompts,
) -> list[SimplifiedClause]:
    """PLANNING.md's verification-failure rule: a self_check-flagged clause
    gets exactly ONE retry. If still flagged after the retry, it is returned
    as-is (self_check remains True) so the frontend renders the warning
    badge — never suppressed, never retried a second time. If the retry
    response drops the clause entirely (malformed/partial), the original
    flagged result is kept rather than lost.
    """
    flagged_ids = {s.id for s in simplified if s.self_check}
    if not flagged_ids:
        return simplified

    to_retry = [c for c in batch if c.id in flagged_ids]
    if not to_retry:
        return simplified

    raw = await client.complete(build_prompt(to_retry))
    retried, _dropped = parse_batch_response(raw, to_retry)
    retried_by_id = {r.id: r for r in retried}

    return [retried_by_id.get(s.id, s) for s in simplified]


def make_verifier(client: CompletesPrompts):
    """Binds a client into a `verify_fn` compatible with
    `simplify_clauses(..., verify_fn=...)`.
    """

    async def verify_fn(
        simplified: list[SimplifiedClause], batch: list[Clause]
    ) -> list[SimplifiedClause]:
        return await retry_flagged_clauses(simplified, batch, client)

    return verify_fn
