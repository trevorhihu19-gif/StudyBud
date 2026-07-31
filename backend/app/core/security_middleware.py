from fastapi import Request
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.core.logging import get_logger

from arcjet import arcjet, detect_bot, shield, Mode, BotCategory

logger = get_logger(__name__)

aj_shield = arcjet(
    key=settings.arcjet_key,
    rules=[
        shield(mode=Mode.LIVE),  
        detect_bot(mode=Mode.LIVE, allow=[BotCategory.MONITOR]), 
    ],
)

async def shield_middleware(request: Request, call_next):
    decision = await aj_shield.protect(request)

    if decision.is_error():
        logger.warning("arcjet_shield_service_error", path=request.url.path)
        return await call_next(request) 

    if decision.is_denied():
        reason_type = decision.reason_v2.type
        logger.warning("request_blocked_globally", reason=reason_type, path=request.url.path)
        status_code = 403
        return JSONResponse(status_code=status_code, content={"error": "Request blocked"})

    return await call_next(request)