import uuid

from sqlalchemy import text

from app.core.database import AsyncSessionLocal
from app.models  import Summary

# Atomic claim: succeeds only if there's no row yet, the last attempt failed,
# or a previous claim has been stuck in 'processing' for 5+ minutes (crashed worker).
_CLAIM_SQL = text("""
    INSERT INTO summaries (id, document_id, status)
    VALUES (:id, :document_id, 'processing')
    ON CONFLICT ON CONSTRAINT uq_summaries_document
    DO UPDATE SET status = 'processing', error_messages = NULL, updated_at = now()
    WHERE summaries.status = 'failed'
       OR (summaries.status = 'processing' AND summaries.updated_at < now() - interval '5 minutes')
    RETURNING id
""")

async def claim_summary(document_id: uuid.UUID) -> uuid.UUID | None:
    async with AsyncSessionLocal() as db, db.begin():
        result = await db.execute(_CLAIM_SQL, {"id": uuid.uuid4(), "document_id": document_id})
        return result.scalar_one_or_none()
    
async def mark_failed(summary_id: uuid.UUID, message: str) -> None:
    async with AsyncSessionLocal() as db, db.begin():
        summary = await db.get(Summary, summary_id)
        if summary is not None:
            summary.status = "failed"
            summary.error_messages = message
            
async def save_ready(
    summary_id: uuid.UUID, overview: str, key_points: list[dict], chunks_used: int, chunks_total: int
) -> Summary:
    async with AsyncSessionLocal() as db, db.begin():
        summary = await db.get(Summary, summary_id)
        summary.status = "ready"
        summary.full_summary = overview
        summary.key_points = key_points
        summary.chunks_used = chunks_used
        summary.chunks_total = chunks_total
        summary.error_messages = None
    return summary