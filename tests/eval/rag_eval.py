"""Score document-context retrieval (app/rag/document_context.py) against
hand-labelled answers in rag_gold.json. Offline and deterministic: no API calls.

    python -m tests.eval.rag_eval            # summary per split
    python -m tests.eval.rag_eval --details  # also list every miss and wrong retrieval

For each clause: are the definitions it uses, and the sections it refers to,
the ones retrieval attached (recall), and is everything attached actually
used (precision)? Plus: is each party's name extracted under the right role?
"""

import argparse
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from app.parsing.clause_splitter import PREAMBLE_HEADING, split_clauses
from app.rag.document_context import attach_context, build_document_context

EVAL_DIR = Path(__file__).resolve().parent
GOLD = EVAL_DIR / "rag_gold.json"
EVAL_SET = EVAL_DIR / "eval_set.json"

_LABEL_RE = re.compile(r"^\s*(?:(?:section|article|clause)\s+)?(\d+(?:\.\d+)*)", re.IGNORECASE)


def clause_label(heading: str | None) -> str | None:
    if heading == PREAMBLE_HEADING:
        return "Preamble"
    match = _LABEL_RE.match(heading or "")
    return match.group(1) if match else None


def load_documents() -> list[dict]:
    gold = json.loads(GOLD.read_text(encoding="utf-8"))["documents"]
    eval_texts = {d["name"]: d["text"] for d in json.loads(EVAL_SET.read_text(encoding="utf-8"))["documents"]}
    return [{**d, "text": eval_texts[d["name"]] if d.get("source") == "eval_set" else d["text"]} for d in gold]


@dataclass
class Counts:
    correct: int = 0
    wrong: int = 0
    missed: int = 0

    def add(self, found: set, expected: set) -> None:
        self.correct += len(found & expected)
        self.wrong += len(found - expected)
        self.missed += len(expected - found)

    @property
    def precision(self) -> float:
        return self.correct / (self.correct + self.wrong) if self.correct + self.wrong else 1.0

    @property
    def recall(self) -> float:
        return self.correct / (self.correct + self.missed) if self.correct + self.missed else 1.0


@dataclass
class Score:
    definitions: Counts = field(default_factory=Counts)
    sections: Counts = field(default_factory=Counts)
    parties_correct: int = 0
    parties_total: int = 0
    parties_wrong: int = 0
    problems: list[str] = field(default_factory=list)


def score_document(document: dict, score: Score) -> None:
    text = document["text"]
    clauses = split_clauses(text)
    index = build_document_context(text, clauses)
    name = document["name"]

    for role, entity in document["parties"].items():
        score.parties_total += 1
        if any(p.startswith(f"{role}: ") and entity in p for p in index.parties):
            score.parties_correct += 1
        else:
            score.problems.append(f"[{name}] party {role} = {entity!r} not extracted; got {index.parties}")

    for term in document.get("not_parties", []):
        if any(p.startswith(f"{term}: ") for p in index.parties):
            score.parties_wrong += 1
            score.problems.append(f"[{name}] {term!r} listed as a party")

    labels = [clause_label(c.heading) for c in clauses]
    unknown = set(document["clauses"]) - set(labels)
    if unknown:
        score.problems.append(f"[{name}] answer key has clauses the splitter did not produce: {sorted(unknown)}")

    for clause, label in zip(attach_context(text, clauses), labels):
        expected = document["clauses"].get(label, {"definitions": [], "sections": []})
        context = clause.context
        found_definitions = set(context.definitions) if context else set()
        found_sections = set(context.referenced_sections) if context else set()
        # a defined term that reaches the clause as a party entry still reaches the model
        delivered_as_party = {p.split(": ", 1)[0] for p in context.parties} if context else set()
        wanted_definitions = set(expected["definitions"])
        found_definitions |= delivered_as_party & wanted_definitions
        score.definitions.add(found_definitions, wanted_definitions)
        score.sections.add(found_sections, set(expected["sections"]))

        for kind, found, wanted in (
            ("definitions", found_definitions, set(expected["definitions"])),
            ("sections", found_sections, set(expected["sections"])),
        ):
            if wanted - found:
                score.problems.append(f"[{name}] {label}: missed {kind} {sorted(wanted - found)}")
            if found - wanted:
                score.problems.append(f"[{name}] {label}: wrong {kind} {sorted(found - wanted)}")


def score_split(split: str | None = None) -> Score:
    score = Score()
    for document in load_documents():
        if split is None or document["split"] == split:
            score_document(document, score)
    return score


def _row(name: str, score: Score) -> str:
    d, s = score.definitions, score.sections
    return (
        f"{name:9s}  definitions P {d.precision:4.0%} R {d.recall:4.0%} ({d.correct}/{d.correct + d.missed}, {d.wrong} wrong)"
        f"   sections P {s.precision:4.0%} R {s.recall:4.0%} ({s.correct}/{s.correct + s.missed}, {s.wrong} wrong)"
        f"   parties {score.parties_correct}/{score.parties_total} ({score.parties_wrong} wrong)"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--details", action="store_true", help="list every miss and wrong retrieval")
    args = parser.parse_args()

    for split in ("eval", "dev", "heldout", "cuad", "cuad_fresh", None):
        score = score_split(split)
        print(_row(split or "all", score))
        if args.details and split is not None:
            for problem in score.problems:
                print(f"    {problem}")


if __name__ == "__main__":
    main()
