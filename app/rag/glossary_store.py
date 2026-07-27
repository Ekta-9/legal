import json
from pathlib import Path

import numpy as np

from app.rag.embeddings import embed_texts

DEFAULT_GLOSSARY_PATH = Path(__file__).resolve().parent / "glossary_data" / "glossary.json"
DEFAULT_TOP_K = 3
DEFAULT_THRESHOLD = 0.35


class GlossaryStore:
    """Numpy-cosine term lookup over a curated glossary — no vector DB.
    A few hundred entries is nothing; embeddings for the whole glossary are
    computed once at construction and held in memory.
    """

    def __init__(self, glossary_path: str | Path = DEFAULT_GLOSSARY_PATH):
        entries = json.loads(Path(glossary_path).read_text(encoding="utf-8"))
        self._terms = [e["term"] for e in entries]
        self._definitions = [e["definition"] for e in entries]
        corpus_texts = [f"{term}: {definition}" for term, definition in zip(self._terms, self._definitions)]
        self._embeddings = embed_texts(corpus_texts)

    def search(
        self, text: str, top_k: int = DEFAULT_TOP_K, threshold: float = DEFAULT_THRESHOLD
    ) -> list[dict]:
        if not text.strip() or len(self._terms) == 0:
            return []

        query_embedding = embed_texts([text])[0]
        scores = self._embeddings @ query_embedding  # unit vectors -> dot product == cosine similarity

        top_indices = np.argsort(-scores)[:top_k]
        results = []
        for idx in top_indices:
            score = float(scores[idx])
            if score < threshold:
                continue
            results.append(
                {"term": self._terms[idx], "definition": self._definitions[idx], "score": round(score, 3)}
            )
        return results
