import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from contextlib import asynccontextmanager
from typing import Literal

from sqlalchemy import text

from app.core.config import settings
from app.core.analytics import track
from app.core.logging import get_logger
from app.core.database import AsyncSessionLocal

logger = get_logger(__name__)
RESOURCE = "llm_tokens"

class QuotaExceeded(Exception):
    def __init__(self, scope: Literal["user", "global"], resets_at: datetime):
        self.scope = scope
        self.resets_at = resets_at
        self.retry_after = max(int(resets_at - datetime.now(UTC)).total_seconds())

def _utc_today() -> date:
    return datetime.now(UTC).date()

def _next_reset(day: date) -> datetime:
    return datetime.combine(day + timedelta(days=1), time.min, tzinfo=UTC)

_INCREMENT_SQL = text("""
    INSERT INTO usage_counters (id, user_id, day, resource, used)
    VALUES (:id, :user_id, :day, :resource, :cost)
    ON CONFLICT ON CONSTRAINT uq_usage_scope_day_resource
    DO UPDATE SET used = usage_counters.used + EXCLUDED.used, updated_at = now()
    WHERE usage_counters.used + EXCLUDED.used <= :limit
    RETURNING used
""")

_ADJUST_SQL = text("""
    UPDATE usage_counters
    SET used = GREATEST(used + :delta, 0), updated_at = now()
    WHERE day = :day AND resource = :resource
      AND (user_id = :user_id OR user_id IS NULL)
""")


async def _try_increment(db, user_id: uuid.UUID | None, day: date, cost: int, limit: int) -> int | None:
    if cost > limit:  # the INSERT path has no limit guard, so reject oversized requests up front
        return None
    result = await db.execute(
        _INCREMENT_SQL,
        {"id": uuid.uuid4(), "user_id": user_id, "day": day, "resource": RESOURCE, "cost": cost, "limit": limit},
    )
    return result.scalar_one_or_none()


@dataclass
class QuotaReservation:
    user_id: uuid.UUID
    day: date
    estimated_tokens: int
    settled: bool = False

    async def _adjust(self, delta: int) -> None:
        async with AsyncSessionLocal() as db, db.begin():
            await db.execute(
                _ADJUST_SQL,
                {"delta": delta, "day": self.day, "resource": RESOURCE, "user_id": self.user_id},
            )

    async def settle(self, actual_tokens: int) -> None:
        """Replace the estimate with the real usage Groq reported."""
        if self.settled:
            return
        delta = max(actual_tokens, 0) - self.estimated_tokens
        if delta:
            await self._adjust(delta)
        self.settled = True


async def reserve(user_id: uuid.UUID, estimated_tokens: int) -> QuotaReservation:
    day = _utc_today()
    denied_scope: str | None = None

    try:
        # One transaction: if the global check fails, the user increment rolls back too
        async with AsyncSessionLocal() as db, db.begin():
            if await _try_increment(db, user_id, day, estimated_tokens, settings.daily_user_token_limit) is None:
                denied_scope = "user"
                raise QuotaExceeded("user", _next_reset(day))
            if await _try_increment(db, None, day, estimated_tokens, settings.daily_global_token_limit) is None:
                denied_scope = "global"
                raise QuotaExceeded("global", _next_reset(day))
    except QuotaExceeded:
        logger.warning("quota_denied", user_id=str(user_id), scope=denied_scope)
        track("quota_denied", user_id=str(user_id), properties={"scope": denied_scope})
        raise
    except Exception:
        # Fail closed: if we can't verify the budget, we don't spend it
        logger.exception("quota_check_failed", user_id=str(user_id))
        raise

    return QuotaReservation(user_id=user_id, day=day, estimated_tokens=estimated_tokens)


@asynccontextmanager
async def llm_quota(user_id: uuid.UUID, estimated_tokens: int):
    """
    async with llm_quota(user.id, estimated_tokens=3000) as q:
        response = await call_groq(...)
        await q.settle(response.usage.total_tokens)
    """
    reservation = await reserve(user_id, estimated_tokens)
    try:
        yield reservation
    except Exception:
        # Errors = no answer delivered. Refund, unless settle() already ran
        # (then the tokens were genuinely spent). Cancellations are NOT
        # Exceptions, so a closed tab never triggers a refund.
        if not reservation.settled:
            await reservation._adjust(-reservation.estimated_tokens)
            reservation.settled = True
        raise


async def get_user_usage(db, user_id: uuid.UUID) -> tuple[int, datetime]:
    day = _utc_today()
    result = await db.execute(
        text("SELECT used FROM usage_counters WHERE user_id = :u AND day = :d AND resource = :r"),
        {"u": user_id, "d": day, "r": RESOURCE},
    )
    return (result.scalar_one_or_none() or 0), _next_reset(day)