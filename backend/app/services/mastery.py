"""Keeps each topic's mastery score (0-100) up to date from the student's answers."""

import uuid

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.ext.asyncio import AsyncSession

RECENT_ANSWERS_COUNT = 20  # mastery = accuracy over this many most recent answers per topic

_LOCK_SQL = text(
    "SELECT id FROM topics WHERE id = ANY(:topic_ids) AND user_id = :user_id ORDER BY id FOR UPDATE"
).bindparams(bindparam("topic_ids", type_=ARRAY(UUID(as_uuid=True))))

_RECOMPUTE_SQL = text("""
    UPDATE topics t
    SET mastery_score = sub.score
    FROM (
        SELECT topic_id, 100.0 * AVG(CASE WHEN is_correct THEN 1 ELSE 0 END) AS score
        FROM (
            SELECT a.topic_id, a.is_correct,
                   ROW_NUMBER() OVER (PARTITION BY a.topic_id ORDER BY att.completed_at DESC, a.id) AS rn
            FROM quiz_attempt_answers a
            JOIN quiz_attempts att ON att.id = a.attempt_id
            WHERE att.user_id = :user_id
              AND att.completed_at IS NOT NULL
              AND a.topic_id = ANY(:topic_ids)
        ) ranked
        WHERE rn <= :recent
        GROUP BY topic_id
    ) sub
    WHERE t.id = sub.topic_id AND t.user_id = :user_id
""").bindparams(bindparam("topic_ids", type_=ARRAY(UUID(as_uuid=True))))


async def update_topic_mastery(db: AsyncSession, user_id: uuid.UUID, topic_ids: set[uuid.UUID]) -> None:
    """Recalculate mastery for the given topics (the caller commits).

    Step 1 locks those topic rows. If two quiz attempts finish at the same moment,
    the second waits for the first to commit, so neither overwrites the other with
    stale numbers. Rows are locked in sorted order to avoid deadlocks.
    Step 2 sets each topic's mastery to the percentage of correct answers among the
    last 20 answers (from completed attempts only).

    Args:
        db: Open database session (same transaction as the attempt completion).
        user_id: Owner of the topics; also enforced in both queries.
        topic_ids: Topics touched by the attempt.
    """
    if not topic_ids:
        return
    ids = list(topic_ids)
    await db.execute(_LOCK_SQL, {"topic_ids": ids, "user_id": user_id})
    await db.execute(_RECOMPUTE_SQL, {"topic_ids": ids, "user_id": user_id, "recent": RECENT_ANSWERS_COUNT})