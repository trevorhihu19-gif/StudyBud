import sentry_sdk
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.starlette import StarletteIntegration

from app.core.config import settings

# Headers must never reach Sentry, even accidentally — auth tokens etc
_SENSITIVE_HEADERS = {"authorization", "cookie", "x-api-key"}

def _before_send(event, hint):
    """Final scrubbing pass before an event leaves the process."""
    request = event.get("request")
    if request and "headers" in request:
        request["headers"] = {
            k: v for k, v in request["headers"].items() if k.lower() not in _SENSITIVE_HEADERS
        }
    return event

def init_sentry() -> None:
    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.environment,
        integrations=[StarletteIntegration(), FastApiIntegration()],
        traces_sample_rate=0.2 if settings.environment == "production" else 1.0,
        send_default_pii=False,     
        before_send=_before_send,
    )