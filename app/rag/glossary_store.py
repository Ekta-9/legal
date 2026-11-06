import json
import re
from pathlib import Path

DEFAULT_GLOSSARY_PATH = Path(__file__).resolve().parent / "glossary_data" / "glossary.json"
DEFAULT_TOP_K = 5

# sentence ends, and blank lines — patterns like "terminate ... breach" must hold within one sentence
_SENTENCE_BREAK_RE = re.compile(r"(?<=[.;!?])\s+|\n\s*\n")


class GlossaryStore:
    """Shows a glossary term only when the clause actually contains it: the
    term's word family ("indemnify" -> Indemnification) or the concept it
    names ("may terminate ... by giving notice" -> Termination for
    Convenience), from the hand-written `patterns` of each entry in
    glossary.json, matched within single sentences. A more specific term
    hides the general one it implies (`suppresses`).

    This replaced an embedding-similarity search, which suggested terms that
    merely sound related ("Statute of Limitations" for a payment clause):
    precision 49% / recall 46% on tests/eval/glossary_gold.json.
    """

    def __init__(self, glossary_path: str | Path = DEFAULT_GLOSSARY_PATH):
        entries = json.loads(Path(glossary_path).read_text(encoding="utf-8"))
        self._entries = [
            {
                "term": e["term"],
                "definition": e["definition"],
                "patterns": [re.compile(p, re.IGNORECASE | re.DOTALL) for p in e.get("patterns", [])],
                "suppresses": set(e.get("suppresses", [])),
            }
            for e in entries
        ]

    def search(self, text: str, top_k: int = DEFAULT_TOP_K) -> list[dict]:
        sentences = [s for s in _SENTENCE_BREAK_RE.split(text) if s.strip()]
        found: list[tuple[int, dict]] = []
        for entry in self._entries:
            position = self._first_match(entry["patterns"], sentences)
            if position is not None:
                found.append((position, entry))

        suppressed = {term for _, entry in found for term in entry["suppresses"]}
        found = [(position, entry) for position, entry in found if entry["term"] not in suppressed]
        found.sort(key=lambda item: item[0])  # in the order the clause raises them
        return [{"term": e["term"], "definition": e["definition"], "score": 1.0} for _, e in found[:top_k]]

    @staticmethod
    def _first_match(patterns: list[re.Pattern], sentences: list[str]) -> int | None:
        offset = 0
        best = None
        for sentence in sentences:
            for pattern in patterns:
                match = pattern.search(sentence)
                if match and (best is None or offset + match.start() < best):
                    best = offset + match.start()
            offset += len(sentence) + 1
        return best
