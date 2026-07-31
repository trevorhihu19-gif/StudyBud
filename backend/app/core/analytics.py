from posthog import Posthog

from app.core.config import settings

posthog = Posthog(settings.posthog_api_key, host=settings.posthog_host)

def track(event: str, user_id: str, properties: dict | None = None) -> None:
    """
    Fire a product analytics event. Never pass email, document content,
     — user_id and metadata only.
    """
    posthog.capture(event, distinct_id=user_id, properties=properties or {})