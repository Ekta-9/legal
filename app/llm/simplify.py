import asyncio
import json
from collections.abc import Callable
from typing import Protocol

from app.constants import GROQ_BATCH_SIZE
from app.llm.groq_client import batch_items
from app.models.schemas import Clause, SimplifiedClause

BatchCallback = Callable[[list[SimplifiedClause], list[str]], None]


class CompletesPrompts(Protocol):
    async def complete(self, prompt: str) -> str: ...


def build_prompt(batch: list[Clause]) -> str:
    items = [{"clause_id": c.id, "text": c.text} for c in batch]
    return (
        "You are simplifying legal contract clauses into plain English for a non-lawyer.\n"
        "For each clause below, produce a simplified version that preserves the original "
        "meaning exactly — do not add, remove, or infer obligations not present in the "
        "source text.\n"
        "Set self_check to true if you are not fully confident the simplification is "
        "faithful to the original, or if the clause is ambiguous or risky to simplify.\n\n"
        f"Clauses:\n{json.dumps(items, indent=2)}\n\n"
        "Respond with ONLY a JSON object of this exact shape:\n"
        '{"results": [{"clause_id": "...", "simplified": "...", "self_check": true|false}]}\n'
        "Include exactly one result per input clause_id, in any order."
    )


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
        simplified.append(
            SimplifiedClause(
                id=clause_id,
                heading=clause.heading,
                original=clause.text,
                simplified=simplified_text.strip(),
                self_check=bool(item.get("self_check", False)),
            )
        )

    dropped = [cid for cid in by_id if cid not in seen_ids]
    return simplified, dropped


async def simplify_clauses(
    clauses: list[Clause],
    client: CompletesPrompts,
    batch_size: int = GROQ_BATCH_SIZE,
    on_batch_complete: BatchCallback | None = None,
) -> tuple[list[SimplifiedClause], list[str]]:
    """Batches clauses, sends each batch to `client`, and merges results.
    Concurrency across batches is bounded by the client's own semaphore.

    `on_batch_complete`, if given, fires as each batch finishes (not just at
    the end) so a caller can stream partial progress — e.g. the job manager
    rendering clauses as they complete rather than waiting for the whole doc.
    """
    batches = batch_items(clauses, batch_size)

    async def process(batch: list[Clause]) -> tuple[list[SimplifiedClause], list[str]]:
        raw = await client.complete(build_prompt(batch))
        result = parse_batch_response(raw, batch)
        if on_batch_complete is not None:
            on_batch_complete(*result)
        return result

    results = await asyncio.gather(*(process(batch) for batch in batches))

    all_simplified: list[SimplifiedClause] = []
    all_dropped: list[str] = []
    for simplified, dropped in results:
        all_simplified.extend(simplified)
        all_dropped.extend(dropped)
    return all_simplified, all_dropped
