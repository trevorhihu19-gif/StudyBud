from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.rate_limit import rate_limit
from app.core.database import get_db
from app.models import User
from app.schemas.search import ChunkResult, SearchRequest
from app.services.retrieval import retrieve

router = APIRouter(prefix="/search", tags=["search"])

@router.post("", response_model=list[ChunkResult])
async def search(
    body: SearchRequest,
    user: User =  Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _: None = Depends(rate_limit),
):
    results = await retrieve(
        db, user_id=user.id, query=body.query, limit=body.limit, document_ids=body.document_ids
    )
    return  [ChunkResult(**r.__dict__) for r in results]