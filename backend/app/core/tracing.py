import os

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

def configure_tracing() -> None:
    """Call once at startup, before any graph runs (the SDK caches env lookups)."""
    if not (settings.langsmith_tracing and settings.langsmith_api_key):
        os.environ["LANGSMITH_TRACING"] = "false"
        logger.info("langsmith_tracing_disabled")
        return
    
    hide_content = settings.environment == "production"
    os.environ["LANGSMITH_TRACING"] = "true"
    os.environ["LANGSMITH_API_KEY"] = settings.langsmith_api_key
    os.environ["LANGSMITH_PROJECT"] = settings.langsmith_project
    # In production, traces keep structure/latency/tokens/errors but not student content
    os.environ["LANGSMITH_HIDE_INPUTS"] = str(hide_content).lower()
    os.environ["LANGSMITH_HIDE_OUTPUTS"] = str(hide_content).lower()
    logger.info("langsmith_tracing_enabled", project=settings.langsmith_project, content_hidden=hide_content)
    
     