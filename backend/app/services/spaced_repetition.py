"""SM-2 spaced repetition: decides when a flashcard should be shown again."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum

MIN_EASE_FACTOR = 1.3
MAX_INTERVAL_DAYS = 365
RELEARN_DELAY = timedelta(minutes=10) # a forgotten card comes back soon, not tomorrow

class Rating(str, Enum):
    """The four buttons a student can press after seeing a card's answer."""

    AGAIN = "again"
    HARD = "hard"
    GOOD = "good"
    EASY = "easy"
    
    # How each button maps to SM-2's 0-5 "quality of recall" scale
_QUALITY = {Rating.AGAIN: 1, Rating.HARD: 3, Rating.GOOD: 4, Rating.EASY: 5}

@dataclass(frozen=True)
class ReviewState:
    """The three numbers SM-2 remembers about a card."""

    ease_factor: float  # how fast the gaps grow (starts at 2.5)
    interval_days: int  # current gap between reviews
    repetitions: int  # successful recalls in a row
    
def schedule_next(state: ReviewState, rating: Rating, now: datetime) -> tuple[ReviewState, datetime]:
    """Work out a card's new schedule after one review.

    Failed (Again): repetitions go back to 0 and the card returns in 10 minutes.
    The ease factor is left alone, as in the original SM-2.
    Passed (Hard/Good/Easy): the gap grows (1 day, then 6 days, then previous gap
    times ease) and the ease factor is nudged down or up based on how hard it felt.
    Gaps are capped at 365 days and ease never drops below 1.3.

    Args:
        state: The card's current ease factor, interval and repetitions.
        rating: The button the student pressed.
        now: The current time (passed in so tests can control it).

    Returns:
        (new_state, next_review_at): the updated numbers and when to show it next.
    """
    quality = _QUALITY[rating]

    if quality < 3:
        return ReviewState(state.ease_factor, 0, 0), now + RELEARN_DELAY

    if state.repetitions == 0:
        interval = 1
    elif state.repetitions == 1:
        interval = 6
    else:
        interval = int(state.interval_days * state.ease_factor + 0.5)  
    interval = min(max(interval, 1), MAX_INTERVAL_DAYS)

    gap = 5 - quality
    ease = max(state.ease_factor + (0.1 - gap * (0.08 + gap * 0.02)), MIN_EASE_FACTOR)

    return ReviewState(round(ease, 2), interval, state.repetitions + 1), now + timedelta(days=interval)
