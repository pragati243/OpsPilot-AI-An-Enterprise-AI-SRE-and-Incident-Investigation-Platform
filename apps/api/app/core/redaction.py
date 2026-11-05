import re

# Shared between the memory policy gate (which rejects content outright)
# and observability masking (which redacts-in-place before export) — one
# definition of "looks like a secret" instead of two that can drift apart.
SECRET_PATTERNS = [
    re.compile(r"(?i)\b(api[_-]?key|secret|password|token)\s*[:=]\s*\S+"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),  # AWS access key id shape
    re.compile(r"\bsk-[A-Za-z0-9]{20,}\b"),  # generic "sk-..." API key shape
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
]

REDACTED_PLACEHOLDER = "[REDACTED]"
DEFAULT_MAX_FIELD_LENGTH = 2000


def contains_secret(text: str) -> bool:
    return any(pattern.search(text) for pattern in SECRET_PATTERNS)


def redact_secrets(text: str) -> str:
    redacted = text
    for pattern in SECRET_PATTERNS:
        redacted = pattern.sub(REDACTED_PLACEHOLDER, redacted)
    return redacted


def truncate(text: str, max_length: int = DEFAULT_MAX_FIELD_LENGTH) -> str:
    if len(text) <= max_length:
        return text
    omitted = len(text) - max_length
    return f"{text[:max_length]}... [truncated {omitted} chars]"
