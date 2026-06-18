"""Local embeddings via sentence-transformers (bge-small, 384 dim).

The model is downloaded once to the HF cache, then loaded from disk. bge models want a
short instruction prefixed to the query (not the documents) for retrieval.
"""
from functools import lru_cache

from app.config import settings

_QUERY_PREFIX = "Represent this sentence for searching relevant passages: "


@lru_cache(maxsize=1)
def _model():
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(settings.embedding_model)


def embed_documents(texts: list[str]):
    """Return an (n, dim) numpy array of normalized document embeddings."""
    return _model().encode(texts, normalize_embeddings=True)


def embed_query(text: str):
    """Return a (dim,) numpy array for a search query."""
    return _model().encode(_QUERY_PREFIX + text, normalize_embeddings=True)
