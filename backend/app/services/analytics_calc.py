"""Pure calculation helpers for the dashboard: streaks, week ranges, percentages, daily plan."""

import math
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, UTC
from zoneinfo import ZoneInfo

MIN_STUDY_SECONDS_FOR_STREAK = 60  # a day only counts if the user studied at least this long
DAILY_GOAL_MINUTES = 30
WEAK_TOPIC_BELOW = 70.0  # mastery under this makes a topic a "revisit" suggestion
WEEKDAY_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


@dataclass(frozen=True)
class StreakInfo:
    """Result of a streak calculation."""

    current: int
    longest: int
    studied_today: bool


def compute_streak(study_days: set[date], today: date) -> StreakInfo:
    """Work out the current and longest run of consecutive study days.

    The current streak counts back from today. If the user hasn't studied yet
    today, it counts back from yesterday, so the streak is still alive until
    the day ends. Days in the future (clock differences) are ignored.

    Args:
        study_days: Local dates on which the user studied enough to count.
        today: Today's date in the user's timezone.

    Returns:
        StreakInfo with the current streak, the longest streak, and whether
        the user has already studied today.
    """
    days = {d for d in study_days if d <= today}
    studied_today = today in days

    cursor = today if studied_today else today - timedelta(days=1)
    current = 0
    while cursor in days:
        current += 1
        cursor -= timedelta(days=1)

    longest = run = 0
    previous: date | None = None
    for d in sorted(days):
        run = run + 1 if previous is not None and d - previous == timedelta(days=1) else 1
        longest = max(longest, run)
        previous = d

    return StreakInfo(current=current, longest=longest, studied_today=studied_today)


def local_midnight_utc(day: date, tz: ZoneInfo) -> datetime:
    """Return the moment a local calendar day starts, expressed in UTC.

    Args:
        day: A date in the user's timezone.
        tz: The user's timezone.

    Returns:
        A timezone-aware UTC datetime for 00:00 local time on that day.
    """
    return datetime.combine(day, time.min, tzinfo=tz).astimezone(UTC)


@dataclass(frozen=True)
class WeekRanges:
    """Date ranges for comparing this week so far with the same span last week."""

    week_start: date  
    days_elapsed: int  # 1 on Monday ... 7 on Sunday
    prev_week_start: date  
    this_start_utc: datetime
    this_end_utc: datetime  
    prev_start_utc: datetime
    prev_end_utc: datetime  


def week_ranges(today: date, tz: ZoneInfo) -> WeekRanges:
    """Build the "this week so far" and "same span last week" ranges.

    Weeks run Monday to Sunday in the user's timezone. Comparing only the days
    that have happened so far keeps "vs last week" fair early in the week.

    Args:
        today: Today's date in the user's timezone.
        tz: The user's timezone.

    Returns:
        A WeekRanges with local dates and matching UTC boundaries.
    """
    week_start = today - timedelta(days=today.weekday())
    elapsed = today.weekday() + 1
    prev_start = week_start - timedelta(days=7)
    return WeekRanges(
        week_start=week_start,
        days_elapsed=elapsed,
        prev_week_start=prev_start,
        this_start_utc=local_midnight_utc(week_start, tz),
        this_end_utc=local_midnight_utc(today + timedelta(days=1), tz),
        prev_start_utc=local_midnight_utc(prev_start, tz),
        prev_end_utc=local_midnight_utc(prev_start + timedelta(days=elapsed), tz),
    )


def percent_change(current: float, previous: float | None) -> float | None:
    """Calculate how much a number changed, as a percentage.

    Args:
        current: This period's value.
        previous: The earlier period's value.

    Returns:
        The change rounded to 1 decimal (for example 12.5), or None when there
        is nothing to compare against (previous is missing or zero).
    """
    if previous is None or previous == 0:
        return None
    return round((current - previous) / previous * 100, 1)


@dataclass(frozen=True)
class PlanItem:
    """One line in "Today's Plan"."""

    kind: str  # study_goal | flashcards | quiz | weak_topic
    title: str
    est_minutes: int | None
    done: bool


def build_daily_plan(
    *,
    studied_seconds_today: int,
    due_flashcards: int,
    total_flashcards: int,
    quizzes_completed_today: int,
    has_ready_document: bool,
    weakest_topic: tuple[str, float] | None,
) -> list[PlanItem]:
    """Build today's checklist using simple rules (no AI, no token cost).

    Rules:
      1. Always: study for the daily goal. Done once enough time is logged today.
      2. If the user has flashcards: review the due ones. Done when none are due.
      3. If the user has a ready document: take a practice quiz. Done once a quiz is finished today.
      4. If a weak topic exists: suggest revisiting it.

    Args:
        studied_seconds_today: Study time logged so far today.
        due_flashcards: Cards due for review right now.
        total_flashcards: All of the user's cards.
        quizzes_completed_today: Quiz attempts finished today (local time).
        has_ready_document: Whether any document has finished processing.
        weakest_topic: (name, mastery) of the weakest eligible topic, or None.

    Returns:
        The plan items in display order.
    """
    plan: list[PlanItem] = []

    goal_seconds = DAILY_GOAL_MINUTES * 60
    remaining_minutes = max(math.ceil((goal_seconds - studied_seconds_today) / 60), 0)
    plan.append(
        PlanItem("study_goal", f"Study for {DAILY_GOAL_MINUTES} minutes", remaining_minutes, studied_seconds_today >= goal_seconds)
    )

    if total_flashcards > 0:
        if due_flashcards > 0:
            noun = "flashcard" if due_flashcards == 1 else "flashcards"
            plan.append(PlanItem("flashcards", f"Review {due_flashcards} {noun}", math.ceil(due_flashcards * 0.5), False))
        else:
            plan.append(PlanItem("flashcards", "Flashcards: all caught up", 0, True))

    if has_ready_document:
        plan.append(PlanItem("quiz", "Take a practice quiz", 10, quizzes_completed_today > 0))

    if weakest_topic is not None:
        name, score = weakest_topic
        plan.append(PlanItem("weak_topic", f"Revisit {name} ({round(score)}% mastery)", 15, False))

    return plan