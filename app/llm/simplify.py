import asyncio
import inspect
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Protocol

from app.config import settings
from app.constants import DROPPED_MAX_RETRIES
from app.llm.facts import missing_numbers
from app.llm.qualifiers import lost_qualifiers
from app.llm.groq_client import batch_items
from app.models.schemas import Clause, ReadabilityScore, SimplifiedClause
from app.scoring.readability import readability_delta

logger = logging.getLogger(__name__)

BatchCallback = Callable[[list[SimplifiedClause], list[str]], Awaitable[None] | None]
ErrorCallback = Callable[[Exception], None]
VerifyFn = Callable[[list[SimplifiedClause], list[Clause]], Awaitable[list[SimplifiedClause]]]


class CompletesPrompts(Protocol):
    async def complete(self, prompt: str) -> str: ...


class ClauseCache(Protocol):
    def get(self, text: str) -> dict | None: ...
    def put(self, text: str, simplified: str, self_check: bool, heading: str | None = None) -> None: ...


def cache_key(clause: Clause) -> str:
    """The same clause text can simplify differently depending on what its
    defined terms and parties mean in a given contract, so retrieved context
    is part of the cache identity. Context-free clauses keep the plain text key.
    """
    if clause.context is None:
        return clause.text
    return f"{clause.text}\n[context]{json.dumps(clause.context.model_dump(), sort_keys=True)}"


def _prompt_item(clause: Clause, problem: str | None = None) -> dict:
    item = {"clause_id": clause.id, "text": clause.text}
    if clause.context is not None:
        item["context"] = clause.context.model_dump(exclude_defaults=True)
    if problem:
        item["previous_attempt_problem"] = problem
    return item


def build_prompt(batch: list[Clause], problems: dict[str, str] | None = None) -> str:
    """`problems` (clause id -> what the previous attempt got wrong) is only
    passed on a retry, so a first attempt's prompt never changes because of it."""
    problems = problems or {}
    items = [_prompt_item(c, problems.get(c.id)) for c in batch]
    retry_note = (
        "Some clauses include a \"previous_attempt_problem\": an earlier simplification of that clause "
        "had this problem. Make sure your new version does not.\n"
        if problems
        else ""
    )
    return (
        "You are simplifying legal contract clauses into plain English for a non-lawyer.\n"
        "For each clause below, produce a simplified version that preserves the original "
        "meaning exactly — do not add, remove, or infer obligations not present in the "
        "source text.\n"
        "Some clauses include a \"context\" object retrieved from elsewhere in the same "
        "contract: the parties, definitions of terms the clause uses, and sections it refers "
        "to. Use it only to interpret the clause correctly (e.g. say who a party is, or what "
        "a defined term means). Do not simplify or restate the context itself, and do not "
        "add obligations that appear only in the context.\n"
        "Refer to parties by their name or role. Do not add details the original does not "
        "state, such as a person's gender or pronouns.\n"
        "Keep every number, amount, date, percentage, deadline and section reference from "
        "the original; write them as digits.\n"
        "Write the way you would explain the clause to a friend with no legal training:\n"
        "- Use everyday words in place of legal wording: shall -> must, prior to -> before, "
        "deemed -> treated as, notwithstanding anything else -> regardless of anything else in "
        "this agreement, hereinafter called -> called, demised premises -> the rented property.\n"
        "- If a legal term has a meaning of its own (for example indemnify, force majeure, "
        "negligence, consequential loss), say what it means in plain words and keep the term once "
        "in brackets.\n"
        "- Turn stock phrases into what they mean: heirs, successors and assigns -> anyone who "
        "later takes over their rights.\n"
        "- Prefer sentences of about 20 words or fewer, but always write full, grammatical sentences.\n"
        "- For a preamble or recitals, say plainly who the parties are and what the agreement is about.\n"
        "Shorter must never mean less. Keep every condition, exception, time limit and override, "
        "and every word that narrows who or what is covered or how something must be done "
        "(for example third-party, written, lawfully, reasonable, other than through a breach).\n"
        "Set self_check to true if you are not fully confident the simplification is "
        "faithful to the original, or if the clause is ambiguous or risky to simplify.\n\n"
        f"{retry_note}"
        f"Clauses:\n{json.dumps(items, indent=2)}\n\n"
        "Respond with ONLY a JSON object of this exact shape:\n"
        '{"results": [{"clause_id": "...", "simplified": "...", "self_check": true|false}]}\n'
        "Include exactly one result per input clause_id, in any order."
    )


def _parse_self_check(value: object) -> bool:
    """A missing or unreadable flag counts as flagged: the badge is the safe
    default when we can't tell. (`bool("false")` would be True, so strings
    are read explicitly.)
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.strip().lower() in ("false", "no", "0"):
        return False
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return bool(value)
    return True


def parse_batch_response(
    raw: str, batch: list[Clause]
) -> tuple[list[SimplifiedClause], list[str]]:
    """Never raises. A malformed/partial response degrades to dropped clause
    ids for the affected clauses rather than crashing the whole document.
    """
    by_id = {c.id: c for c in batch}

    try:
        data = json.loads(raw)
        results = data["results"]
        if not isinstance(results, list):
            raise ValueError("'results' is not a list")
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        return [], list(by_id.keys())

    simplified: list[SimplifiedClause] = []
    seen_ids: set[str] = set()
    for item in results:
        if not isinstance(item, dict):
            continue
        clause_id = item.get("clause_id")
        if clause_id not in by_id or clause_id in seen_ids:
            continue
        simplified_text = item.get("simplified")
        if not isinstance(simplified_text, str) or not simplified_text.strip():
            continue
        seen_ids.add(clause_id)
        clause = by_id[clause_id]
        stripped_simplified = simplified_text.strip()
        simplified.append(
            SimplifiedClause(
                id=clause_id,
                heading=clause.heading,
                original=clause.text,
                simplified=stripped_simplified,
                self_check=_parse_self_check(item.get("self_check")),
                missing_numbers=missing_numbers(clause.text, stripped_simplified),
                lost_qualifiers=lost_qualifiers(clause.text, stripped_simplified),
                readability=ReadabilityScore(**readability_delta(clause.text, stripped_simplified)),
            )
        )

    dropped = [cid for cid in by_id if cid not in seen_ids]
    return simplified, dropped


async def simplify_clauses(
    clauses: list[Clause],
    client: CompletesPrompts,
    batch_size: int | None = None,
    on_batch_complete: BatchCallback | None = None,
    cache: ClauseCache | None = None,
    verify_fn: VerifyFn | None = None,
    on_batch_error: ErrorCallback | None = None,
) -> tuple[list[SimplifiedClause], list[str]]:
    """Batches clauses, sends each batch to `client`, and merges results.
    Concurrency across batches is bounded by the client's own semaphore.

    `on_batch_complete`, if given, fires as each batch finishes (not just at
    the end) so a caller can stream partial progress — e.g. the job manager
    rendering clauses as they complete rather than waiting for the whole doc.

    `cache`, if given, is checked before every clause is sent to the LLM and
    written through after each batch — cache hits never touch `client` at all.

    `verify_fn`, if given, runs after each batch's initial results and before
    caching/callback — e.g. `app.llm.verify`'s flag-then-retry-once rule. It
    is decoupled here via injection (rather than an import) so this module
    has no dependency on the verification policy.

    A batch whose LLM call raises (after the client's own retries) does not
    abort the other batches: its clauses are reported as dropped and the
    exception is passed to `on_batch_error`. Results the model flagged as
    unsure, or that lost a number or a qualifier from the original, are not
    cached, so a later run gets a fresh attempt.
    `on_batch_complete` may be sync or async.
    """
    to_process: list[Clause] = []
    cached_simplified: list[SimplifiedClause] = []
    for clause in clauses:
        hit = cache.get(cache_key(clause)) if cache is not None else None
        if hit is not None:
            cached_simplified.append(
                SimplifiedClause(
                    id=clause.id,
                    heading=clause.heading,
                    original=clause.text,
                    simplified=hit["simplified"],
                    self_check=hit["self_check"],
                    missing_numbers=missing_numbers(clause.text, hit["simplified"]),
                    lost_qualifiers=lost_qualifiers(clause.text, hit["simplified"]),
                    readability=ReadabilityScore(
                        **readability_delta(clause.text, hit["simplified"])
                    ),
                )
            )
        else:
            to_process.append(clause)

    async def report(simplified: list[SimplifiedClause], dropped: list[str]) -> None:
        if on_batch_complete is None:
            return
        result = on_batch_complete(simplified, dropped)
        if inspect.isawaitable(result):
            await result

    if cached_simplified:
        await report(cached_simplified, [])

    batches = batch_items(to_process, batch_size or settings.groq_batch_size)

    async def simplify_batch(batch: list[Clause]) -> tuple[list[SimplifiedClause], list[str]]:
        raw = await client.complete(build_prompt(batch))
        simplified, dropped = parse_batch_response(raw, batch)
        for _ in range(DROPPED_MAX_RETRIES):
            if not dropped:
                break
            missing = [c for c in batch if c.id in set(dropped)]
            recovered, dropped = parse_batch_response(await client.complete(build_prompt(missing)), missing)
            simplified.extend(recovered)
        if verify_fn is not None:
            simplified = await verify_fn(simplified, batch)
        return simplified, dropped

    async def process(batch: list[Clause]) -> tuple[list[SimplifiedClause], list[str]]:
        try:
            simplified, dropped = await simplify_batch(batch)
        except Exception as e:
            logger.exception("Batch of %d clauses failed", len(batch))
            if on_batch_error is not None:
                on_batch_error(e)
            simplified, dropped = [], [c.id for c in batch]
        if dropped:
            logger.warning("%d clause(s) not simplified: %s", len(dropped), ", ".join(dropped))
        if cache is not None:
            by_id = {c.id: c for c in batch}
            for s in simplified:
                if not s.self_check and not s.missing_numbers and not s.lost_qualifiers:
                    cache.put(cache_key(by_id[s.id]), s.simplified, s.self_check, s.heading)
        await report(simplified, dropped)
        return simplified, dropped

    results = await asyncio.gather(*(process(batch) for batch in batches))

    all_simplified: list[SimplifiedClause] = list(cached_simplified)
    all_dropped: list[str] = []
    for simplified, dropped in results:
        all_simplified.extend(simplified)
        all_dropped.extend(dropped)
    return all_simplified, all_dropped
