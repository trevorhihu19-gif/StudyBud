from datetime import datetime ,UTC
from app.services.spaced_repetition import Rating, ReviewState, schedule_next

now = datetime.now(UTC)
state = ReviewState(2.5, 0, 0)
for _ in range(5):
    state, due = schedule_next(state, Rating.GOOD, now)
    print(state.interval_days, state.ease_factor)