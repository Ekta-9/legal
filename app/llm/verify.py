from app.llm.simplify import CompletesPrompts, build_prompt, parse_batch_response
from app.models.schemas import Clause, SimplifiedClause


def _problem_count(result: SimplifiedClause) -> int:
    return len(result.missing_numbers) + len(result.lost_qualifiers)


def _describe(result: SimplifiedClause) -> str:
    """What the code checks found, told to the model on the retry."""
    parts = []
    if result.missing_numbers:
        parts.append(f"it left out these numbers from the original: {', '.join(result.missing_numbers)}")
    if result.lost_qualifiers:
        parts.append(f"it lost or reversed {' and '.join(result.lost_qualifiers)} that the original has")
    return "; ".join(parts)


async def retry_flagged_clauses(
    simplified: list[SimplifiedClause],
    batch: list[Clause],
    client: CompletesPrompts,
) -> list[SimplifiedClause]:
    """PLANNING.md's verification-failure rule: a clause that is flagged —
    by the model's own self_check, or by the code checks finding a number or
    a qualifier ("notwithstanding") from the original missing — gets exactly
    ONE retry, told what the first attempt lost. If still flagged after the
    retry, it is returned as-is so the frontend renders the warning — never
    suppressed, never retried a second time. If the retry response drops the
    clause entirely (malformed/partial), or has more problems than the first
    attempt, the first result is kept.
    """
    flagged = {s.id: s for s in simplified if s.self_check or s.missing_numbers or s.lost_qualifiers}
    if not flagged:
        return simplified

    to_retry = [c for c in batch if c.id in flagged]
    if not to_retry:
        return simplified

    problems = {clause_id: _describe(s) for clause_id, s in flagged.items() if _describe(s)}
    raw = await client.complete(build_prompt(to_retry, problems))
    retried, _dropped = parse_batch_response(raw, to_retry)
    retried_by_id = {r.id: r for r in retried}

    def better(first: SimplifiedClause) -> SimplifiedClause:
        retry = retried_by_id.get(first.id)
        if retry is None or _problem_count(retry) > _problem_count(first):
            return first
        return retry

    return [better(s) for s in simplified]


def make_verifier(client: CompletesPrompts):
    """Binds a client into a `verify_fn` compatible with
    `simplify_clauses(..., verify_fn=...)`.
    """

    async def verify_fn(
        simplified: list[SimplifiedClause], batch: list[Clause]
    ) -> list[SimplifiedClause]:
        return await retry_flagged_clauses(simplified, batch, client)

    return verify_fn
