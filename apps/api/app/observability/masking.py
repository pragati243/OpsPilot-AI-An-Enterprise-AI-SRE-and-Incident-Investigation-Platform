from typing import Any

from app.core.redaction import redact_secrets, truncate

_MAX_STRING_LENGTH = 2000
_SENSITIVE_KEY_MARKERS = (
    "authorization",
    "api_key",
    "apikey",
    "secret",
    "password",
    "token",
    "cookie",
)


def _mask_value(value: Any) -> Any:
    if isinstance(value, str):
        return truncate(redact_secrets(value), _MAX_STRING_LENGTH)
    if isinstance(value, dict):
        return {
            key: (
                "[REDACTED]"
                if isinstance(key, str)
                and any(marker in key.lower() for marker in _SENSITIVE_KEY_MARKERS)
                else _mask_value(val)
            )
            for key, val in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_mask_value(item) for item in value]
    return value


def mask_data(*, data: Any, **_kwargs: Any) -> Any:
    """Langfuse's global `mask` hook — applied to every span/generation's
    input, output, and metadata before it leaves the process. Redacts
    secret-shaped substrings, blanks keys that look sensitive by name, and
    truncates long strings (e.g. a raw log dump) rather than shipping them
    verbatim to an external service. This is the backstop; call sites
    should still avoid capturing full tool output in the first place where
    they can (see app/observability/serialization.py).
    """
    return _mask_value(data)
