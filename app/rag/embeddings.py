from functools import lru_cache

import numpy as np
from sentence_transformers import SentenceTransformer

MODEL_NAME = "all-MiniLM-L6-v2"


@lru_cache(maxsize=1)
def get_model() -> SentenceTransformer:
    return SentenceTransformer(MODEL_NAME)


def embed_texts(texts: list[str]) -> np.ndarray:
    """Unit-normalized embeddings, so cosine similarity reduces to a dot
    product in glossary_store.py.
    """
    if not texts:
        dim = get_model().get_sentence_embedding_dimension()
        return np.empty((0, dim), dtype=np.float32)
    embeddings = get_model().encode(texts, convert_to_numpy=True, normalize_embeddings=True)
    return embeddings.astype(np.float32)
