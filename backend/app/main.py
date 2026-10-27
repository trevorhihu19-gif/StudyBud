from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from functools import partial

from app.models import User
from app.core.config import settings
from app.core.database import get_db
from app.core.logging import configure_logging, get_logger, new_request_id
from app.api.deps import get_current_user
from app.core.rate_limit import rate_limit
from app.core.security_middleware import shield_middleware
from app.routes.documents import router as documents_router
from app.routes.search import router as search_router
from app.routes.chat import router as chat_router
from app.routes.summaries import router as summaries_router
from app.services.quota import QuotaExceeded
from app.agents.llm import LLMUnavailable
from app.core.tracing import configure_tracing

configure_logging()
configure_tracing()
logger = get_logger(__name__)



app = FastAPI(title="StudyBud", version="0.1.0")

_QUOTA_MESSAGES = {
    "user": "You've reached your daily AI limit. It resets at midnight UTC.",
    "global": "StudyBud's free daily AI capacity has been used up. Please try again after it resets at midnight UTC.",
}

@app.middleware("http")
async def add_request_id_middleware(request: Request, call_next):
    request_id = new_request_id()
    logger.info("request_started", method=request.method, path=request.url.path)
    response = await call_next(request)
    logger.info("request_finished", method=request.method, path=request.url.path, status_code=response.status_code)
    response.headers["X-Request-ID"] = request_id
    return response

@app.middleware("http")
async def shield_middleware_wrapper(request: Request, call_next):
    return await shield_middleware(request, call_next)

@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    logger.warning("http_exception", status_code=exc.status_code, detail=exc.detail, path=request.url.path)
    return JSONResponse(status_code=exc.status_code, content={"error": exc.detail})


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    logger.warning("validation_error", errors=exc.errors(), path=request.url.path)
    return JSONResponse(status_code=422, content={"error": "Invalid request data", "details": exc.errors()})

@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.error("unhandled_exception", path=request.url.path, error=str(exc), exc_info=True)
    return JSONResponse(status_code=500, content={"error": "Internal server error"})

@app.exception_handler(QuotaExceeded)
async def quota_exceeded_handler(request: Request, exc: QuotaExceeded):
    return JSONResponse(
        status_code=429,
        content={
            "error":_QUOTA_MESSAGES[exc.scope],
            "code": f"{exc.scope}_daily_limit",
            "resets_at": exc.resets_at.isoformat(),
        },
        headers={"Retry-After": str(exc.retry_after)}
    )

@app.exception_handler(LLMUnavailable)
async def llm_unavailable_handler(request: Request, exc: LLMUnavailable):
    logger.warning("llm_unavailable", path=request.url.path)
    return JSONResponse(
        status_code=503,
        content={"error": "The AI is busy right now. Please try again later.", "code": "llm_busy"},
        headers={"Retry-After": "30"},
    )

@app.get("/health")
async def health_check():
    return {"status": "ok", "environment": settings.environment}

@app.get("/health/whoami")
async def whoami(user: User = Depends(get_current_user), _: None = Depends(rate_limit)):
    return {"user_id": str(user.id), "email": user.email}

@app.get("/health/db")
async def health_check_db(db: AsyncSession = Depends(get_db)):
    result = await db.execute(text("SELECT 1"))
    return {"status": "ok", "db_result": result.scalar()}

app.include_router(documents_router)
app.include_router(search_router)
app.include_router(chat_router)
app.include_router(summaries_router)

@app.post("/quizzes/generate")
async def generate_quiz(
    user: User = Depends(get_current_user),
    _: None = Depends(partial(rate_limit, requested=10)),
):
    ...