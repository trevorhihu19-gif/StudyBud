"""Endpoints about the logged-in user's own settings."""

from functools import lru_cache
from zoneinfo import available_timezones

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.rate_limit import rate_limit
from app.core.database import get_db
from app.models import User
from app.schemas.analytics import TimezoneIn

router = APIRouter(prefix="/users/me", tags=["users"])


@lru_cache(maxsize=1)
def _valid_timezones() -> frozenset[str]:
    """List every timezone name the system knows (read once, then remembered)."""
    
    return frozenset(available_timezones())


@router.put("/timezone")
async def set_timezone(
    body: TimezoneIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _: None = Depends(rate_limit),
):
    """Save the user's timezone (the frontend sends the browser's, e.g. "Africa/Nairobi").

    Only real IANA names are accepted. Streaks and weekly stats use this to decide
    where one day ends and the next begins.
    """
    if body.timezone not in _valid_timezones():
        raise HTTPException(status_code=422, detail="Unknown timezone")
    user.timezone = body.timezone  
    await db.commit()
    return {"timezone": user.timezone}