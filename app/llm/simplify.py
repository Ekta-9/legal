import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import Protocol

from app.constants import DROPPED_MAX_RETRIES, GROQ_BATCH_SIZE
from app.llm.groq_client import batch_items
from app.models.schemas import Clause, ReadabilityScore, SimplifiedClause
from app.scoring.readability import readability_delta

BatchCallback = Callable[[list[SimplifiedClause], list[str]], None]
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


def _prompt_item(clause: Clause) -> dict:
    item = {"clause_id": clause.id, "text": clause.text}
    if clause.context is not None:
        item["context"] = clause.context.model_dump(exclude_defaults=True)
    return item


def build_prompt(batch: list[Clause]) -> str:
    items = [_prompt_item(c) for c in batch]
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
        "Set self_check to true if you are not fully confident the simplification is "
        "faithful to the original, or if the clause is ambiguous or risky to simplify.\n\n"
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
                readability=ReadabilityScore(**readability_delta(clause.text, stripped_simplified)),
            )
        )

    dropped = [cid for cid in by_id if cid not in seen_ids]
    return simplified, dropped


async def simplify_clauses(
    clauses: list[Clause],
    client: CompletesPrompts,
    batch_size: int = GROQ_BATCH_SIZE,
    on_batch_complete: BatchCallback | None = None,
    cache: ClauseCache | None = None,
    verify_fn: VerifyFn | None = None,
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
                    readability=ReadabilityScore(
                        **readability_delta(clause.text, hit["simplified"])
                    ),
                )
            )
        else:
            to_process.append(clause)

    if cached_simplified and on_batch_complete is not None:
        on_batch_complete(cached_simplified, [])

    batches = batch_items(to_process, batch_size)

    async def process(batch: list[Clause]) -> tuple[list[SimplifiedClause], list[str]]:
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
        if cache is not None:
            by_id = {c.id: c for c in batch}
            for s in simplified:
                cache.put(cache_key(by_id[s.id]), s.simplified, s.self_check, s.heading)
        if on_batch_complete is not None:
            on_batch_complete(simplified, dropped)
        return simplified, dropped

    results = await asyncio.gather(*(process(batch) for batch in batches))

    all_simplified: list[SimplifiedClause] = list(cached_simplified)
    all_dropped: list[str] = []
    for simplified, dropped in results:
        all_simplified.extend(simplified)
        all_dropped.extend(dropped)
    return all_simplified, all_dropped
