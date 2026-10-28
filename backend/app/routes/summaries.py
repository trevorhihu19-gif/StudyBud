import uuid
from functools import partial

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.summary_graph import SummaryContext, SummaryGenerationError, summary_graph
from app.api.deps import get_current_user
from app.core.analytics import track
from app.core.logging import get_logger, request_id_var
from app.core.rate_limit import rate_limit
from app.core.database import get_db
from app.models import Document, DocumentStatus, Summary, User
from app.schemas.summary import SummaryResponse
from app.services.summary_store import claim_summary, mark_failed, save_ready

router = APIRouter(prefix="/documents/{document_id}/summary", tags=["summaries"])
logger = get_logger(__name__)

def _to_response(s: Summary) -> SummaryResponse:
    return SummaryResponse(
        document_id=s.document_id,
        status=s.status,
        overview=s.full_summary,
        key_points=s.key_points or [],
        chunks_used=s.chunks_used,
        chunks_total=s.chunks_total,
        error=s.error_messages,
        created_at=s.created_at,
    )
    
async def _owned_document(db: AsyncSession, user_id: uuid.UUID, document_id: uuid.UUID) -> Document:
    result = await db.execute(select(Document).where(Document.id == document_id, Document.user_id == user_id))
    document = result.scalar_one_or_none()
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found") 
    return document

async def _load_summary(db: AsyncSession, document_id: uuid.UUID) -> Summary | None:
    result = await db.execute(select(Summary).where(Summary.document_id == document_id))
    return result.scalar_one_or_none()


@router.get("", response_model=SummaryResponse)
async def get_summary(
    document_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _:None = Depends(rate_limit)
):
    await _owned_document(db, user.id, document_id)
    summary = await _load_summary(db, document_id)
    if summary is None:
        raise HTTPException(status_code=404, detail="No summary yet")
    return _to_response(summary)

@router.post("", response_model=SummaryResponse)
async def create_summary(
    document_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _: None = Depends(partial(rate_limit, requested=5)),
):
    document = await _owned_document(db, user.id, document_id)
    if document.status == DocumentStatus.PROCESSING:
        raise HTTPException(status_code=409, detail="This document is still being processed")
    if document.status == DocumentStatus.FAILED:
        raise HTTPException(status_code=422, detail="This document could not be processed")
    
    existing = await _load_summary(db, document_id)
    if existing is not None and existing.status == "ready":
        return _to_response(existing) # idempotent: zero tokens spent
    await db.commit()  # release the pooled connection before the slow LLM call
    
    claim_id = await claim_summary(document_id)
    if claim_id is None:
        # Lost the race. Maybe the winner already finished
        current = await _load_summary(db, document_id)
        if current is not None and current.status == "ready":
            return _to_response(current)
        raise HTTPException(status_code=409, detail="A summary is already being generated for this document")
    
    try:
        result = await summary_graph.ainvoke(
            {"document_id": str(document_id)},
            context=SummaryContext(user_id=user.id),
            config={
                "tags": ["summary"],
                "metadata": {"user_id": str(user.id), "request_id": request_id_var.get()},
            }
        )
    except SummaryGenerationError as e:
        await mark_failed(claim_id, str(e))
        raise HTTPException(status_code=502, detail=str(e))
    except Exception:
        # Includes QuotaExceeded and LLMUnavailable: release the claim so a retry can succeed,
        # then let the global handlers turn it into the right 429/503/500
        await mark_failed(claim_id, "Summary generation failed. Please try again.")
        raise
    
    summary = await save_ready(
        claim_id,
        result["overview"],
        result["key_points"],
        len(result["chunks"]),
        result["chunks_total"],
    )
    
    logger.info(
        "summary_generated",
        user_id=str(user.id),
        document_id=str(document_id),
        chunks_used=len(result["chunks"]),
        chunks_total=result["chunks_total"]
    )
    track("summary_generated", user_id=str(user.id), properties={"chunks_used": len(result["chunks"])})
    return _to_response(summary)
        
    
    