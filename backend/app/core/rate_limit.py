from fastapi import Depends, HTTPException, Request, status

from app.api.deps import get_current_user
from app.core.config import settings
from app.core.logging import get_logger
from app.models import User

from arcjet import arcjet, token_bucket, Mode

logger = get_logger(__name__)

aj_ratelimit = arcjet(
    key=settings.arcjet_key,
    rules=[
        token_bucket(
            characteristics=["userId"],
            mode=Mode.LIVE,
            refill_rate=20,
            interval=60,
            capacity=100,
        ),
    ],
)

async def rate_limit(
    request: Request,
    user: User = Depends(get_current_user),
    requested: int = 1,
) -> None:
    decision = await aj_ratelimit.protect(
        request,
        requested=requested,
        characteristics={"userId": str(user.id)},
    )

    if decision.is_error():
        logger.warning("arcjet_ratelimit_service_error", user_id=str(user.id))
        return

    if decision.is_denied():
        logger.warning("rate_limit_exceeded", user_id=str(user.id), path=request.url.path)
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Rate limit exceeded")