"""Response shapes for the dashboard, plus the study-time and timezone requests."""

import datetime as dt
import uuid
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.quiz import WeakTopicOut


class StreakOut(BaseModel):
    """Study streak numbers (the flame on the dashboard)."""

    current_days: int
    longest_days: int
    studied_today: bool


class DayBar(BaseModel):
    """One bar in the weekly study-time chart."""

    day: dt.date
    label: str  # Mon, Tue, ...
    seconds: int


class WeekOut(BaseModel):
    """This week so far, compared with the same span of last week. A change of null means "nothing to compare"."""

    study_seconds: int
    study_seconds_change_percent: float | None
    daily: list[DayBar]  # always 7 entries, Monday to Sunday
    quizzes_taken: int
    quizzes_taken_change_percent: float | None
    avg_score_percent: float | None
    avg_score_change_points: float | None  # percentage points, e.g. +7.0


class FlashcardCounts(BaseModel):
    """Flashcards due now and in total."""

    due_count: int
    total_count: int


class ContinueStudyingItem(BaseModel):
    """A document in the "Continue Studying" list."""

    document_id: uuid.UUID
    title: str
    file_type: str
    progress_percent: float
    last_studied_at: dt.datetime


class RecentSummaryItem(BaseModel):
    """A summary in the "Recent Summaries" list."""

    document_id: uuid.UUID
    title: str
    generated_at: dt.datetime


class PlanItemOut(BaseModel):
    """One checklist line in "Today's Plan"."""

    kind: str
    title: str
    est_minutes: int | None
    done: bool


class DashboardResponse(BaseModel):
    """Everything the dashboard and the mobile Progress screen need, in one call."""

    timezone: str
    streak: StreakOut
    week: WeekOut
    overall_avg_score_percent: float | None  # last 30 days, for the score ring
    topics_mastered: int
    weak_areas: list[WeakTopicOut]
    flashcards: FlashcardCounts
    continue_studying: list[ContinueStudyingItem]
    recent_summaries: list[RecentSummaryItem]
    today_plan: list[PlanItemOut]


class StudySessionIn(BaseModel):
    """A chunk of study time reported by the frontend."""

    client_ref: uuid.UUID  # random id made by the client; makes retries safe
    activity_type: Literal["reading", "quiz", "flashcards", "chat"]
    duration_seconds: int = Field(ge=1, le=3600)


class StudySessionOut(BaseModel):
    """What the server did with a study-time report."""

    recorded: bool  # false for a duplicate retry, or when the daily cap was already reached
    counted_seconds: int


class TimezoneIn(BaseModel):
    """Body for setting the user's timezone."""

    timezone: str = Field(min_length=1, max_length=64)