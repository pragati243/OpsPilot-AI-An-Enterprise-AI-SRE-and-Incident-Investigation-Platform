import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import DocumentSourceType
from app.retrieval.embeddings import embed_query

# Reciprocal Rank Fusion constant — the standard default (e.g. Elasticsearch
# uses 60), not tuned against a held-out dataset for this project.
_RRF_K = 60
_CANDIDATE_LIMIT = 25
# Cosine distance cutoff for the vector leg (0 = identical, 2 = opposite).
# Without this, pgvector's <=> always returns its closest K rows even for a
# query unrelated to anything in the corpus — "best of a bad lot" isn't a
# match. 0.5 is a heuristic picked by checking real on-topic vs. off-topic
# query distances against the seed corpus (~0.28-0.33 vs. ~0.60), not a
# tuned threshold from an eval dataset.
_MAX_VECTOR_DISTANCE = 0.5

_HYBRID_SEARCH_SQL = text("""
    WITH vector_matches AS (
        SELECT id, ROW_NUMBER() OVER (
            ORDER BY embedding <=> CAST(:query_embedding AS vector)
        ) AS rnk
        FROM documents
        WHERE tenant_id = :tenant_id
          AND source_type = CAST(:source_type AS document_source_type)
          AND embedding IS NOT NULL
          AND embedding <=> CAST(:query_embedding AS vector) < :max_vector_distance
          AND (array_length(access_scope, 1) IS NULL OR access_scope && :allowed_scopes)
        ORDER BY embedding <=> CAST(:query_embedding AS vector)
        LIMIT :candidate_limit
    ),
    text_matches AS (
        SELECT id, ROW_NUMBER() OVER (
            ORDER BY ts_rank(search_vector, plainto_tsquery('english', :raw_query)) DESC
        ) AS rnk
        FROM documents
        WHERE tenant_id = :tenant_id
          AND source_type = CAST(:source_type AS document_source_type)
          AND search_vector @@ plainto_tsquery('english', :raw_query)
          AND (array_length(access_scope, 1) IS NULL OR access_scope && :allowed_scopes)
        LIMIT :candidate_limit
    ),
    fused AS (
        SELECT
            COALESCE(v.id, t.id) AS id,
            (CASE WHEN v.rnk IS NOT NULL THEN 1.0 / (:rrf_k + v.rnk) ELSE 0 END)
            + (CASE WHEN t.rnk IS NOT NULL THEN 1.0 / (:rrf_k + t.rnk) ELSE 0 END) AS score
        FROM vector_matches v
        FULL OUTER JOIN text_matches t ON v.id = t.id
    )
    SELECT d.id, d.title, d.content, f.score
    FROM fused f
    JOIN documents d ON d.id = f.id
    ORDER BY f.score DESC
    LIMIT :result_limit
""")


def _vector_literal(values: list[float]) -> str:
    return "[" + ",".join(repr(v) for v in values) + "]"


class HybridMatch:
    __slots__ = ("id", "title", "content", "score")

    def __init__(self, id: uuid.UUID, title: str, content: str, score: float) -> None:
        self.id = id
        self.title = title
        self.content = content
        self.score = score


async def hybrid_search_documents(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    source_type: DocumentSourceType,
    query: str,
    allowed_scopes: set[str],
    limit: int,
) -> list[HybridMatch]:
    """Dense (pgvector cosine distance) + full-text (Postgres tsvector)
    retrieval over Documents, fused with Reciprocal Rank Fusion. ACL
    filtering (access_scope) is applied inside both legs of the SQL, not in
    Python after the fact, so a restricted document never even reaches the
    candidate set for a caller who can't see it.
    """
    query_vector = await embed_query(query)

    result = await db.execute(
        _HYBRID_SEARCH_SQL,
        {
            "query_embedding": _vector_literal(query_vector),
            "raw_query": query,
            "tenant_id": tenant_id,
            # SQLAlchemy's Enum() column stores the Python member *name*
            # (e.g. "RUNBOOK"), not `.value` ("runbook") — this raw SQL has
            # to match that directly since there's no ORM type coercion
            # on this path.
            "source_type": source_type.name,
            "allowed_scopes": list(allowed_scopes),
            "candidate_limit": _CANDIDATE_LIMIT,
            "max_vector_distance": _MAX_VECTOR_DISTANCE,
            "rrf_k": _RRF_K,
            "result_limit": limit,
        },
    )
    return [HybridMatch(**row._mapping) for row in result]
