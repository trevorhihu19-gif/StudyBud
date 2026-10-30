"""The dashboard endpoint: one call that returns every number the dashboard shows."""

from datetime import datetime, timedelta, UTC
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.rate_limit import rate_limit
from app.core.database import get_db
from app.models import User
from app.schemas.analytics import (
    ContinueStudyingItem, DashboardResponse, DayBar, FlashcardCounts, PlanItemOut,
    RecentSummaryItem, StreakOut, WeekOut,
)
from app.schemas.quiz import WeakTopicOut
from app.services import analytics as q
from app.services.analytics_calc import (
    WEAK_TOPIC_BELOW, WEEKDAY_LABELS, build_daily_plan, compute_streak, local_midnight_utc,
    percent_change, week_ranges,
)

router = APIRouter(prefix="/analytics", tags=["analytics"])


def _user_timezone(name: str) -> ZoneInfo:
    """Turn the user's saved timezone name into a ZoneInfo, falling back to UTC if it can't be loaded."""
    try:
        return ZoneInfo(name)
    except Exception:
        return ZoneInfo("UTC")


@router.get("/dashboard", response_model=DashboardResponse)
async def dashboard(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _: None = Depends(rate_limit),
):
    """Return all dashboard numbers for the logged-in user.

    Days and weeks follow the user's own timezone. "This week" means Monday until
    now, compared against the same number of days last week. Runs about ten small
    indexed queries, one after another (one session = one connection).
    """
    tz = _user_timezone(user.timezone)
    now_utc = datetime.now(UTC)
    today = now_utc.astimezone(tz).date()
    r = week_ranges(today, tz)

    # --- Streak ---
    streak = compute_streak(await q.get_study_days(db, user.id, user.timezone), today)

    # --- Study time (one query covers last week's start through today) ---
    daily = await q.get_daily_study_seconds(db, user.id, user.timezone, r.prev_start_utc, r.this_end_utc)
    this_seconds = sum(daily.get(r.week_start + timedelta(days=i), 0) for i in range(r.days_elapsed))
    prev_seconds = sum(daily.get(r.prev_week_start + timedelta(days=i), 0) for i in range(r.days_elapsed))
    bars = [
        DayBar(day=(d := r.week_start + timedelta(days=i)), label=WEEKDAY_LABELS[i], seconds=daily.get(d, 0))
        for i in range(7)
    ]

    # --- Quizzes ---
    taken, avg_score = await q.get_quiz_stats(db, user.id, r.this_start_utc, r.this_end_utc)
    prev_taken, prev_avg = await q.get_quiz_stats(db, user.id, r.prev_start_utc, r.prev_end_utc)
    today_taken, _avg = await q.get_quiz_stats(db, user.id, local_midnight_utc(today, tz), r.this_end_utc)
    _count, overall_avg = await q.get_quiz_stats(db, user.id, now_utc - timedelta(days=30), r.this_end_utc)

    # --- Topics, flashcards, documents ---
    mastered = await q.get_topics_mastered(db, user.id)
    weak = await q.get_weak_topics(db, user.id, 5)
    due, total = await q.get_flashcard_counts(db, user.id)
    continue_studying = await q.get_continue_studying(db, user.id, 3)
    summaries = await q.get_recent_summaries(db, user.id, 3)

    # --- Today's plan (rules only, no AI) ---
    weakest = next((t for t in weak if t["mastery_score"] < WEAK_TOPIC_BELOW and t["answered_count"] >= 3), None)
    plan = build_daily_plan(
        studied_seconds_today=daily.get(today, 0),
        due_flashcards=due,
        total_flashcards=total,
        quizzes_completed_today=today_taken,
        has_ready_document=bool(continue_studying),
        weakest_topic=(weakest["name"], weakest["mastery_score"]) if weakest else None,
    )

    return DashboardResponse(
        timezone=user.timezone,
        streak=StreakOut(current_days=streak.current, longest_days=streak.longest, studied_today=streak.studied_today),
        week=WeekOut(
            study_seconds=this_seconds,
            study_seconds_change_percent=percent_change(this_seconds, prev_seconds),
            daily=bars,
            quizzes_taken=taken,
            quizzes_taken_change_percent=percent_change(taken, prev_taken),
            avg_score_percent=avg_score,
            avg_score_change_points=round(avg_score - prev_avg, 1) if avg_score is not None and prev_avg is not None else None,
        ),
        overall_avg_score_percent=overall_avg,
        topics_mastered=mastered,
        weak_areas=[WeakTopicOut(**t) for t in weak],
        flashcards=FlashcardCounts(due_count=due, total_count=total),
        continue_studying=[ContinueStudyingItem(**c) for c in continue_studying],
        recent_summaries=[RecentSummaryItem(**s) for s in summaries],
        today_plan=[PlanItemOut(kind=p.kind, title=p.title, est_minutes=p.est_minutes, done=p.done) for p in plan],
    )