"""Score glossary term matching (app/rag/glossary_store.py) against hand-labelled
answers in glossary_gold.json. Offline.

    python -m tests.eval.glossary_eval            # summary for both splits
    python -m tests.eval.glossary_eval --details  # every wrong and missed term

dev:     the tests/eval contracts; the patterns were written against these
heldout: real CUAD contracts labelled before the patterns were run on them

precision: of the terms shown under a clause, how many are relevant to it
recall:    of the relevant terms, how many are shown
"""

import argparse
import json
from pathlib import Path

from app.parsing.clause_splitter import is_heading_only, is_signature_block, split_clauses

EVAL_DIR = Path(__file__).resolve().parent
GOLD = EVAL_DIR / "glossary_gold.json"
EVAL_SET = EVAL_DIR / "eval_set.json"


def _skipped(text: str) -> bool:
    # as the app does: titles and signature lines are never simplified, so no terms are shown for them
    return is_heading_only(text) or is_signature_block(text)


def _clauses(split: str):
    """(document name, clause key, clause text) — keyed by heading for dev, clause number for heldout."""
    gold = json.loads(GOLD.read_text(encoding="utf-8"))
    if split == "dev":
        for document in json.loads(EVAL_SET.read_text(encoding="utf-8"))["documents"]:
            labels = gold["documents"].get(document["name"], {})
            for clause in split_clauses(document["text"]):
                if not _skipped(clause.text):
                    yield document["name"], labels.get(clause.heading, []), clause.heading, clause.text
    else:
        from tests.eval.rag_eval import clause_label, load_documents

        texts = {d["name"]: d["text"] for d in load_documents()}
        for name, labels in gold["heldout"].items():
            for clause in split_clauses(texts[name]):
                if _skipped(clause.text):
                    continue
                key = clause_label(clause.heading)
                yield name, labels.get(key, []), key, clause.text


def score(search, split: str = "dev") -> dict:
    """`search(text) -> list[dict]` with a "term" key, like GlossaryStore.search."""
    correct = wrong = missed = 0
    problems = []
    for name, labels, key, text in _clauses(split):
        shown = {m["term"] for m in search(text)}
        expected = set(labels)
        correct += len(shown & expected)
        wrong += len(shown - expected)
        missed += len(expected - shown)
        if shown != expected:
            problems.append(f"[{name}] {key}: wrong {sorted(shown - expected)} missed {sorted(expected - shown)}")
    return {
        "correct": correct,
        "wrong": wrong,
        "missed": missed,
        "precision": correct / (correct + wrong) if correct + wrong else 1.0,
        "recall": correct / (correct + missed) if correct + missed else 1.0,
        "problems": problems,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--details", action="store_true")
    args = parser.parse_args()

    from app.rag.glossary_store import GlossaryStore

    store = GlossaryStore()
    for split in ("dev", "heldout"):
        result = score(store.search, split)
        print(
            f"{split:8s} precision {result['precision']:4.0%}  recall {result['recall']:4.0%}  "
            f"({result['correct']} correct, {result['wrong']} wrong, {result['missed']} missed)"
        )
        if args.details:
            for problem in result["problems"]:
                print(f"    {problem}")


if __name__ == "__main__":
    main()
