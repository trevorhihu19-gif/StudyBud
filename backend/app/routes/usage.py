from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.config import settings
from app.core.rate_limit import rate_limit
from app.core.database import get_db
from app.models import User
from app.services.quota import get_user_usage

router = APIRouter(prefix="/usage", tags=["usage"])

class UsageResponse(BaseModel):
    used: int
    limit: int
    remaining: int
    resets_at: datetime
    
@router.get("", response_model=UsageResponse)
async def usage(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _:None = Depends(rate_limit),
):
    used, resets_at = await get_user_usage(db, user.id)
    limit = settings.daily_user_token_limit
    return UsageResponse(used=used, limit=limit, remaining=max(limit - used, 0), resets_at=resets_at)