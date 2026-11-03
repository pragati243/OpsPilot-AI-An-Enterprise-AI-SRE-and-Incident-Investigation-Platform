import asyncio
from functools import lru_cache

from fastembed import TextEmbedding

from app.models.document import EMBEDDING_DIMENSION

EMBEDDING_MODEL_NAME = "BAAI/bge-small-en-v1.5"

assert EMBEDDING_DIMENSION == 384  # bge-small-en-v1.5's native output size


@lru_cache
def _get_model() -> TextEmbedding:
    # Loaded once per process (ONNX, CPU, no torch) — the first call in a
    # process pays model-load cost, every call after is cheap.
    return TextEmbedding(model_name=EMBEDDING_MODEL_NAME)


async def embed_query(text: str) -> list[float]:
    """Embed a search query. BGE models are trained asymmetrically — queries
    get an instruction prefix that passages don't, which is why this isn't
    just `embed_passages([text])[0]`.
    """

    def _run() -> list[float]:
        (vector,) = list(_get_model().query_embed([text]))
        return vector.tolist()

    return await asyncio.to_thread(_run)


async def embed_passages(texts: list[str]) -> list[list[float]]:
    """Embed documents being indexed."""
    if not texts:
        return []

    def _run() -> list[list[float]]:
        return [vector.tolist() for vector in _get_model().passage_embed(texts)]

    return await asyncio.to_thread(_run)
