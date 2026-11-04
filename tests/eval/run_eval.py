"""Compare Groq models on the hand-written evaluation contracts.

Runs each document through the same steps as the app (split, retrieve
context, simplify with the verify retry, no cache) and scores the result.
Uses your Groq quota: roughly 4-8 calls per model.

    python -m tests.eval.run_eval --model openai/gpt-oss-20b --model openai/gpt-oss-120b

Scores are coarse checks, not a judgement of legal accuracy:
  returned   clauses that came back at all
  numbers    clauses where every number from the original survived
  concepts   required concepts (eval_set.json "expect") found in the plain version
  unsure     clauses the model flagged with self_check
  grade      mean Flesch-Kincaid grade, original -> plain (lower is easier)
"""

import argparse
import asyncio
import json
import re
import statistics
import time
from pathlib import Path

from app.llm.groq_client import GroqClient
from app.llm.simplify import simplify_clauses
from app.llm.verify import make_verifier
from app.parsing.clause_splitter import split_clauses
from app.rag.document_context import attach_context

EVAL_SET = Path(__file__).resolve().parent / "eval_set.json"


def _plain(text: str) -> str:
    # models sometimes write non-breaking or typographic hyphens ("sub‑let")
    return re.sub(r"[‐-―]", "-", text).lower()


def concept_misses(simplified: str, concepts: list[list[str]]) -> list[str]:
    text = _plain(simplified)
    return [" / ".join(words) for words in concepts if not any(w.lower() in text for w in words)]


async def evaluate(model: str, documents: list[dict]) -> dict:
    client = GroqClient(model=model)
    rows = []
    started = time.perf_counter()
    for document in documents:
        clauses = attach_context(document["text"], split_clauses(document["text"]))
        simplified, dropped = await simplify_clauses(clauses, client, verify_fn=make_verifier(client))
        by_id = {s.id: s for s in simplified}
        for clause in clauses:
            result = by_id.get(clause.id)
            concepts = document["expect"].get(clause.heading, [])
            rows.append(
                {
                    "document": document["name"],
                    "heading": clause.heading,
                    "returned": result is not None,
                    "simplified": result.simplified if result else "",
                    "missing_numbers": result.missing_numbers if result else [],
                    "concepts_total": len(concepts),
                    "concept_misses": concept_misses(result.simplified, concepts) if result else [" / ".join(c) for c in concepts],
                    "self_check": bool(result and result.self_check),
                    "grade_before": result.readability.original_grade if result and result.readability else None,
                    "grade_after": result.readability.simplified_grade if result and result.readability else None,
                }
            )
    return {"model": model, "seconds": round(time.perf_counter() - started, 1), "rows": rows}


def summarize(run: dict) -> dict:
    rows = run["rows"]
    returned = [r for r in rows if r["returned"]]
    concepts_total = sum(r["concepts_total"] for r in rows)
    concepts_missed = sum(len(r["concept_misses"]) for r in rows)
    graded = [r for r in returned if r["grade_before"] is not None]
    return {
        "model": run["model"],
        "returned": f"{len(returned)}/{len(rows)}",
        "numbers": f"{sum(1 for r in returned if not r['missing_numbers'])}/{len(rows)}",
        "concepts": f"{concepts_total - concepts_missed}/{concepts_total}",
        "unsure": str(sum(1 for r in rows if r["self_check"])),
        "grade": (
            f"{statistics.mean(r['grade_before'] for r in graded):.1f} -> "
            f"{statistics.mean(r['grade_after'] for r in graded):.1f}"
            if graded else "-"
        ),
        "seconds": str(run["seconds"]),
    }


def print_report(runs: list[dict]) -> None:
    summaries = [summarize(run) for run in runs]
    columns = ["model", "returned", "numbers", "concepts", "unsure", "grade", "seconds"]
    widths = {c: max(len(c), *(len(s[c]) for s in summaries)) for c in columns}
    print("  ".join(c.ljust(widths[c]) for c in columns))
    for s in summaries:
        print("  ".join(s[c].ljust(widths[c]) for c in columns))

    for run in runs:
        problems = [r for r in run["rows"] if not r["returned"] or r["missing_numbers"] or r["concept_misses"]]
        print(f"\n{run['model']}: {len(problems)} clause(s) with problems")
        for r in problems:
            issues = []
            if not r["returned"]:
                issues.append("not returned")
            if r["missing_numbers"]:
                issues.append("numbers lost: " + ", ".join(r["missing_numbers"]))
            if r["concept_misses"]:
                issues.append("concepts missing: " + "; ".join(r["concept_misses"]))
            print(f"  [{r['document']}] {r['heading']}: {' | '.join(issues)}")
            if r["simplified"]:
                print(f"      -> {r['simplified']}")


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--model", action="append", required=True, help="Groq model id; repeat to compare")
    parser.add_argument("--out", type=Path, help="also write the full per-clause results as JSON")
    args = parser.parse_args()

    documents = json.loads(EVAL_SET.read_text(encoding="utf-8"))["documents"]
    runs = [await evaluate(model, documents) for model in args.model]
    print_report(runs)
    if args.out:
        args.out.write_text(json.dumps(runs, indent=2, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(main())
