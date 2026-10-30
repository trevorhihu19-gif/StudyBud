"""Endpoint where the frontend reports how long the student studied."""

from datetime import datetime, timedelta, UTC

from fastapi import APIRouter, Depends
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.routes.analytics import _user_timezone
from app.api.deps import get_current_user
from app.core.rate_limit import rate_limit
from app.core.database import get_db
from app.models import StudySession, User
from app.schemas.analytics import StudySessionIn, StudySessionOut
from app.services.analytics import get_daily_study_seconds
from app.services.analytics_calc import local_midnight_utc

router = APIRouter(prefix="/study-sessions", tags=["analytics"])

MAX_DAILY_STUDY_SECONDS = 16 * 3600  # keeps stats believable even if a client misbehaves


@router.post("", response_model=StudySessionOut)
async def report_study_time(
    body: StudySessionIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _: None = Depends(rate_limit),
):
    """Record a chunk of study time (the frontend sends one about every minute while studying).

    The server decides WHEN it happened (now), ignoring any client clock. Retrying
    the same client_ref is safe: it is ignored the second time. Time beyond 16 hours
    per local day is not counted.
    """
    tz = _user_timezone(user.timezone)
    today = datetime.now(UTC).astimezone(tz).date()
    start = local_midnight_utc(today, tz)

    used_today = sum((await get_daily_study_seconds(db, user.id, user.timezone, start, start + timedelta(days=1))).values())
    counted = max(min(body.duration_seconds, MAX_DAILY_STUDY_SECONDS - used_today), 0)
    if counted == 0:
        return StudySessionOut(recorded=False, counted_seconds=0)

    inserted = await db.execute(
        pg_insert(StudySession)
        .values(
            user_id=user.id,
            client_ref=body.client_ref,
            activity_type=body.activity_type,
            duration_seconds=counted,
        )
        .on_conflict_do_nothing(constraint="uq_study_session_client_ref")
        .returning(StudySession.id)
    )
    recorded = inserted.scalar_one_or_none() is not None
    await db.commit()
    return StudySessionOut(recorded=recorded, counted_seconds=counted if recorded else 0)