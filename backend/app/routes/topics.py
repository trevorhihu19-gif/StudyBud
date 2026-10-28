"""Topic endpoints: the data behind the Weak Areas panel."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.rate_limit import rate_limit
from app.core.database import get_db
from app.models import User
from app.schemas.quiz import WeakTopicOut

router = APIRouter(prefix="/topics", tags=["topics"])


@router.get("/weak", response_model=list[WeakTopicOut])
async def weak_topics(
    limit: int = Query(default=5, ge=1, le=20),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _: None = Depends(rate_limit),
):
    """List the user's lowest-mastery topics, weakest first.

    Only topics the student has actually answered questions on are included.
    (Topics created by quiz generation start at 0%, and would otherwise look
    like the student's weakest before they've tried a single question.)
    """
    rows = await db.execute(
        text("""
            SELECT t.id, t.name, t.mastery_score, COUNT(a.id) AS answered
            FROM topics t
            JOIN quiz_attempt_answers a ON a.topic_id = t.id
            JOIN quiz_attempts att ON att.id = a.attempt_id AND att.completed_at IS NOT NULL
            WHERE t.user_id = :user_id
            GROUP BY t.id
            ORDER BY t.mastery_score ASC
            LIMIT :limit
        """),
        {"user_id": user.id, "limit": limit},
    )
    return [
        WeakTopicOut(topic_id=r.id, name=r.name, mastery_score=round(r.mastery_score, 1), answered_count=r.answered)
        for r in rows
    ]