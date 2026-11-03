import math

from app.models.document import EMBEDDING_DIMENSION
from app.retrieval.embeddings import embed_passages, embed_query


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    return dot / (norm_a * norm_b)


async def test_embed_query_has_expected_dimension() -> None:
    vector = await embed_query("database connection pool exhausted")
    assert len(vector) == EMBEDDING_DIMENSION


async def test_embed_passages_has_expected_dimension_and_count() -> None:
    vectors = await embed_passages(["first document", "second document"])
    assert len(vectors) == 2
    assert all(len(v) == EMBEDDING_DIMENSION for v in vectors)


async def test_embed_passages_empty_list_returns_empty() -> None:
    assert await embed_passages([]) == []


async def test_embed_is_deterministic() -> None:
    first = await embed_query("connection pool exhaustion")
    second = await embed_query("connection pool exhaustion")
    assert first == second


async def test_semantically_similar_text_scores_higher_than_unrelated() -> None:
    (pool_a, pool_b, cake) = await embed_passages(
        [
            "The database connection pool is exhausted under peak load.",
            "Postgres is running out of connections because the pool is too small.",
            "Preheat the oven and mix flour, sugar, and eggs for a cake.",
        ]
    )

    sim_related = _cosine_similarity(pool_a, pool_b)
    sim_unrelated = _cosine_similarity(pool_a, cake)

    assert sim_related > sim_unrelated
