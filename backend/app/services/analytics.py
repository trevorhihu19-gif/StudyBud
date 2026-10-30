"""Database queries behind the dashboard. Every query is scoped to one user and uses bound parameters."""

import uuid
from datetime import date, datetime, timedelta, UTC

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.analytics_calc import MIN_STUDY_SECONDS_FOR_STREAK

STREAK_LOOKBACK_DAYS = 730
MASTERED_THRESHOLD = 80.0  # topic counts as "mastered" at or above this mastery score...
MASTERED_MIN_ANSWERS = 5   # ...with at least this many answers behind it


async def get_study_days(db: AsyncSession, user_id: uuid.UUID, tz_name: str) -> set[date]:
    """List the local dates on which the user studied enough to count for a streak.

    Groups study sessions by the user's local calendar day, and keeps days with
    at least 60 seconds of study.

    Args:
        db: Open database session.
        user_id: The user.
        tz_name: The user's IANA timezone name, passed as a bound parameter.

    Returns:
        A set of local dates (looking back about two years).
    """
    since = datetime.now(UTC) - timedelta(days=STREAK_LOOKBACK_DAYS)
    rows = await db.execute(
        text("""
            SELECT (occurred_at AT TIME ZONE :tz)::date AS day
            FROM study_sessions
            WHERE user_id = :user_id AND occurred_at >= :since
            GROUP BY 1
            HAVING SUM(duration_seconds) >= :min_seconds
        """),
        {"tz": tz_name, "user_id": user_id, "since": since, "min_seconds": MIN_STUDY_SECONDS_FOR_STREAK},
    )
    return {r.day for r in rows}


async def get_daily_study_seconds(
    db: AsyncSession, user_id: uuid.UUID, tz_name: str, start_utc: datetime, end_utc: datetime
) -> dict[date, int]:
    """Total study seconds per local day within a time range.

    Args:
        db: Open database session.
        user_id: The user.
        tz_name: The user's IANA timezone name.
        start_utc: Range start (inclusive).
        end_utc: Range end (exclusive).

    Returns:
        Dict mapping local date to seconds studied. Days with no study are absent.
    """
    rows = await db.execute(
        text("""
            SELECT (occurred_at AT TIME ZONE :tz)::date AS day, SUM(duration_seconds)::bigint AS seconds
            FROM study_sessions
            WHERE user_id = :user_id AND occurred_at >= :start AND occurred_at < :end
            GROUP BY 1
        """),
        {"tz": tz_name, "user_id": user_id, "start": start_utc, "end": end_utc},
    )
    return {r.day: int(r.seconds) for r in rows}


async def get_quiz_stats(
    db: AsyncSession, user_id: uuid.UUID, start_utc: datetime, end_utc: datetime
) -> tuple[int, float | None]:
    """Count finished quiz attempts and average their scores within a time range.

    Args:
        db: Open database session.
        user_id: The user.
        start_utc: Range start (inclusive).
        end_utc: Range end (exclusive).

    Returns:
        (attempts_completed, average_score_percent). The average is None if there were no attempts.
    """
    row = (
        await db.execute(
            text("""
                SELECT COUNT(*) AS taken, AVG(score_percent) AS avg_score
                FROM quiz_attempts
                WHERE user_id = :user_id AND completed_at >= :start AND completed_at < :end
            """),
            {"user_id": user_id, "start": start_utc, "end": end_utc},
        )
    ).one()
    return int(row.taken), (round(float(row.avg_score), 1) if row.avg_score is not None else None)


async def get_topics_mastered(db: AsyncSession, user_id: uuid.UUID) -> int:
    """Count topics the student has mastered (high mastery backed by enough answers).

    Args:
        db: Open database session.
        user_id: The user.

    Returns:
        The number of mastered topics.
    """
    result = await db.execute(
        text("""
            SELECT COUNT(*) FROM (
                SELECT t.id
                FROM topics t
                JOIN quiz_attempt_answers a ON a.topic_id = t.id
                JOIN quiz_attempts att ON att.id = a.attempt_id AND att.completed_at IS NOT NULL
                WHERE t.user_id = :user_id AND t.mastery_score >= :threshold
                GROUP BY t.id
                HAVING COUNT(a.id) >= :min_answers
            ) mastered
        """),
        {"user_id": user_id, "threshold": MASTERED_THRESHOLD, "min_answers": MASTERED_MIN_ANSWERS},
    )
    return int(result.scalar_one())


async def get_weak_topics(db: AsyncSession, user_id: uuid.UUID, limit: int) -> list[dict]:
    """List the user's lowest-mastery topics, weakest first.

    Only topics with at least one answer from a finished attempt are included.
    (A topic created by quiz generation starts at 0% and would otherwise look
    like the weakest before the student has tried a single question.)

    Args:
        db: Open database session.
        user_id: The user.
        limit: Maximum number of topics to return.

    Returns:
        Dicts with topic_id, name, mastery_score and answered_count.
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
        {"user_id": user_id, "limit": limit},
    )
    return [
        {"topic_id": r.id, "name": r.name, "mastery_score": round(r.mastery_score, 1), "answered_count": r.answered}
        for r in rows
    ]


async def get_flashcard_counts(db: AsyncSession, user_id: uuid.UUID) -> tuple[int, int]:
    """Count the user's flashcards: how many are due now, and how many exist.

    Args:
        db: Open database session.
        user_id: The user.

    Returns:
        (due_count, total_count).
    """
    row = (
        await db.execute(
            text("""
                SELECT COUNT(*) AS total, COUNT(*) FILTER (WHERE next_review_at <= now()) AS due
                FROM flashcards WHERE user_id = :user_id
            """),
            {"user_id": user_id},
        )
    ).one()
    return int(row.due), int(row.total)


async def get_continue_studying(db: AsyncSession, user_id: uuid.UUID, limit: int) -> list[dict]:
    """List the documents the student worked on most recently, with a progress percentage.

    Progress = distinct quiz questions answered correctly at least once, divided
    by all quiz questions made from that document (0 if it has no quizzes).
    Recency = the later of the upload time and the last finished quiz attempt.

    Args:
        db: Open database session.
        user_id: The user.
        limit: Maximum number of documents.

    Returns:
        Dicts with document_id, title, file_type, progress_percent and last_studied_at.
    """
    rows = await db.execute(
        text("""
            WITH totals AS (
                SELECT qz.document_id, COUNT(qq.id) AS total_questions
                FROM quizzes qz JOIN quiz_questions qq ON qq.quiz_id = qz.id
                WHERE qz.user_id = :user_id AND qz.document_id IS NOT NULL
                GROUP BY qz.document_id
            ),
            correct AS (
                SELECT qz.document_id, COUNT(DISTINCT a.question_id) AS correct_questions
                FROM quiz_attempt_answers a
                JOIN quiz_attempts att ON att.id = a.attempt_id AND att.completed_at IS NOT NULL
                JOIN quiz_questions qq ON qq.id = a.question_id
                JOIN quizzes qz ON qz.id = qq.quiz_id
                WHERE att.user_id = :user_id AND a.is_correct AND qz.document_id IS NOT NULL
                GROUP BY qz.document_id
            ),
            last_attempt AS (
                SELECT qz.document_id, MAX(att.completed_at) AS last_at
                FROM quiz_attempts att JOIN quizzes qz ON qz.id = att.quiz_id
                WHERE att.user_id = :user_id AND att.completed_at IS NOT NULL AND qz.document_id IS NOT NULL
                GROUP BY qz.document_id
            )
            SELECT d.id AS document_id, d.title, d.file_type,
                   LEAST(100.0, COALESCE(100.0 * c.correct_questions / NULLIF(t.total_questions, 0), 0)) AS progress,
                   GREATEST(d.created_at, COALESCE(la.last_at, d.created_at)) AS last_studied_at
            FROM documents d
            LEFT JOIN totals t ON t.document_id = d.id
            LEFT JOIN correct c ON c.document_id = d.id
            LEFT JOIN last_attempt la ON la.document_id = d.id
            WHERE d.user_id = :user_id AND d.status = 'READY'
            ORDER BY last_studied_at DESC
            LIMIT :limit
        """),
        {"user_id": user_id, "limit": limit},
    )
    return [
        {
            "document_id": r.document_id,
            "title": r.title,
            "file_type": r.file_type,
            "progress_percent": round(float(r.progress), 1),
            "last_studied_at": r.last_studied_at,
        }
        for r in rows
    ]


async def get_recent_summaries(db: AsyncSession, user_id: uuid.UUID, limit: int) -> list[dict]:
    """List the user's most recently generated summaries.

    Args:
        db: Open database session.
        user_id: The user.
        limit: Maximum number of summaries.

    Returns:
        Dicts with document_id, title and generated_at, newest first.
    """
    rows = await db.execute(
        text("""
            SELECT d.id AS document_id, d.title, s.updated_at AS generated_at
            FROM summaries s JOIN documents d ON d.id = s.document_id
            WHERE d.user_id = :user_id AND s.status = 'ready'
            ORDER BY s.updated_at DESC
            LIMIT :limit
        """),
        {"user_id": user_id, "limit": limit},
    )
    return [{"document_id": r.document_id, "title": r.title, "generated_at": r.generated_at} for r in rows]