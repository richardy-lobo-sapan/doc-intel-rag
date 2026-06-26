"""
Local embedding model wrapper.

Model choice: intfloat/multilingual-e5-base.
  - Multilingual: internal SOP/regulatory corpora in a real deployment are
    very likely to mix Indonesian and English (regulatory language often
    stays in Indonesian even when surrounding docs are in English) — a
    English-only model like all-MiniLM-L6-v2 would degrade badly on that.
  - 768-dim, runs comfortably on CPU for a corpus of this size (no GPU
    dependency for a small-to-medium scale demo).
  - E5 models require a "query: " / "passage: " prefix convention during
    training; we replicate that here (embed_query vs embed_passages) since
    skipping it measurably hurts retrieval quality for E5 specifically.
"""

from __future__ import annotations

from functools import lru_cache

from sentence_transformers import SentenceTransformer

from app.config import settings


@lru_cache(maxsize=1)
def get_model() -> SentenceTransformer:
    return SentenceTransformer(settings.embedding_model_name)


def embed_passages(texts: list[str]) -> list[list[float]]:
    model = get_model()
    prefixed = [f"passage: {t}" for t in texts]
    vectors = model.encode(prefixed, normalize_embeddings=True, show_progress_bar=False)
    return vectors.tolist()


def embed_query(text: str) -> list[float]:
    model = get_model()
    vector = model.encode(f"query: {text}", normalize_embeddings=True, show_progress_bar=False)
    return vector.tolist()
