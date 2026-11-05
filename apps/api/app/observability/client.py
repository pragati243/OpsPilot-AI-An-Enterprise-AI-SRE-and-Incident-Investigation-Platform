from functools import lru_cache

from langfuse import Langfuse

from app.core.config import get_settings
from app.observability.masking import mask_data


@lru_cache
def get_langfuse_client() -> Langfuse:
    """One client per process. `tracing_enabled` is explicitly derived from
    whether both keys are present — without a key, calls through this
    client (and every `@observe`-decorated function in the codebase) are
    inert no-ops rather than a crash, so instrumentation never has to be
    conditionally skipped at call sites just because a dev/CI environment
    has no Langfuse project configured.
    """
    settings = get_settings()
    configured = bool(settings.langfuse_public_key and settings.langfuse_secret_key)
    return Langfuse(
        public_key=settings.langfuse_public_key or None,
        secret_key=settings.langfuse_secret_key or None,
        host=settings.langfuse_host,
        mask=mask_data,
        environment=settings.env,
        tracing_enabled=configured,
    )
