import uuid
from dataclasses import dataclass

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.services.embeddings import embed_query

logger = get_logger(__name__)

RRF_K = 60
CANDIDATES_PER_SEARCH = 30


_DOC_FILTER = "AND d.id = ANY(:document_ids)"  # static fragment, never built from user input

_SQL = """
WITH vector_hits AS (
    SELECT id, ROW_NUMBER() OVER (ORDER BY distance) AS rank
    FROM (
        SELECT c.id, c.embedding <=> CAST(:query_embedding AS vector) AS distance
        FROM document_chunks c
        JOIN documents d ON d.id = c.document_id
        WHERE d.user_id = :user_id
          AND d.status = 'READY'
          AND c.embedding IS NOT NULL
          {doc_filter}
        ORDER BY distance
        LIMIT :candidates
    ) t
),
keyword_hits AS (
    SELECT id, ROW_NUMBER() OVER (ORDER BY score DESC) AS rank
    FROM (
        SELECT c.id,
               ts_rank_cd(c.content_tsv, websearch_to_tsquery('english', :query_text)) AS score
        FROM document_chunks c
        JOIN documents d ON d.id = c.document_id
        WHERE d.user_id = :user_id
          AND d.status = 'READY'
          AND c.content_tsv @@ websearch_to_tsquery('english', :query_text)
          {doc_filter}
        ORDER BY score DESC
        LIMIT :candidates
    ) t
),
fused AS (
    SELECT COALESCE(v.id, k.id) AS id,
           COALESCE(1.0 / (:rrf_k + v.rank), 0) + COALESCE(1.0 / (:rrf_k + k.rank), 0) AS score
    FROM vector_hits v
    FULL OUTER JOIN keyword_hits k ON v.id = k.id
)
SELECT c.id, c.document_id, c.page_number, c.content, f.score
FROM fused f
JOIN document_chunks c ON c.id = f.id
ORDER BY f.score DESC
LIMIT :limit
"""


@dataclass
class RetrievedChunk:
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    page_number: int | None
    content: str
    score: float


async def retrieve(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,  
    query: str,
    limit: int = 5,
    document_ids: list[uuid.UUID] | None = None,
) -> list[RetrievedChunk]:
    embedding = await embed_query(query)
    embedding_literal = "[" + ",".join(str(x) for x in embedding) + "]"

    # Iterative scan keeps the HNSW index scanning until enough rows survive
    # the user/status filter. SET LOCAL lasts only for this transaction.
    await db.execute(text("SET LOCAL hnsw.iterative_scan = 'relaxed_order'"))
    await db.execute(text("SET LOCAL hnsw.ef_search = 100"))

    sql = _SQL.format(doc_filter=_DOC_FILTER if document_ids else "")
    stmt = text(sql)
    if document_ids:
        stmt = stmt.bindparams(bindparam("document_ids", type_=ARRAY(UUID(as_uuid=True))))

    params = {
        "query_embedding": embedding_literal,
        "query_text": query,
        "user_id": user_id,
        "candidates": CANDIDATES_PER_SEARCH,
        "rrf_k": RRF_K,
        "limit": limit,
    }
    if document_ids:
        params["document_ids"] = document_ids

    rows = (await db.execute(stmt, params)).all()

    logger.info(
        "retrieval_completed",
        user_id=str(user_id),
        query_length=len(query),  
        results=len(rows),
        scoped_to_documents=bool(document_ids),
    )

    return [
        RetrievedChunk(
            chunk_id=r.id,
            document_id=r.document_id,
            page_number=r.page_number,
            content=r.content,
            score=float(r.score),
        )
        for r in rows
    ]