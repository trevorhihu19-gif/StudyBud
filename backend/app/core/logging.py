import logging
import sys
import uuid
from contextvars import ContextVar
import structlog

from app.core.config import settings

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")

def _add_request_id(logger, method_name, event_dict):
    event_dict["request_id"] = request_id_var.get()
    return event_dict

def configure_logging() -> None:
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=logging.INFO)

    shared_processors = [
        structlog.contextvars.merge_contextvars,
        _add_request_id,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
    ]

    if settings.environment == "production":
        renderer = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer()  

    structlog.configure(
        processors=shared_processors + [renderer],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )

def get_logger(name: str = "studybud"):
    return structlog.get_logger(name)

def new_request_id() -> str:
    rid = str(uuid.uuid4())
    request_id_var.set(rid)
    return rid