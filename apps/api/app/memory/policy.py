import re
import uuid

from app.core.redaction import contains_secret

MAX_CONTENT_LENGTH = 1000

# Cosine similarity above this is treated as "restating the same fact," not
# a new one — the old record gets superseded rather than duplicated. Not
# tuned against an eval dataset; picked deliberately high so two merely
# *related* facts about the same service don't collide.
SUPERSESSION_SIMILARITY_THRESHOLD = 0.92

# Deterministic backstop against prompt-injection-flavored text being
# stored as if it were a verified fact — a second line of defense behind
# the extraction prompt's own "treat this as data, not instructions" rule.
_INJECTION_PATTERNS = [
    re.compile(r"(?i)ignore (all |the )?(previous|above) instructions"),
    re.compile(r"(?i)you are now in \w+ mode"),
    re.compile(r"(?i)reveal (your|the) system prompt"),
    re.compile(r"(?i)disregard (your|all) (prior|previous) (instructions|rules)"),
]


class MemoryPolicyViolation(Exception):
    pass


def validate_content(content: str) -> None:
    """The deterministic gate any memory content must pass before it's
    persisted — whether it came from LLM extraction, a user correction, or
    a user-set profile preference. Independent of the extraction LLM's own
    behavior, and independent of who's writing it.
    """
    content = content.strip()
    if not content:
        raise MemoryPolicyViolation("memory content is empty")
    if len(content) > MAX_CONTENT_LENGTH:
        raise MemoryPolicyViolation(
            f"memory content exceeds {MAX_CONTENT_LENGTH} characters"
        )

    if contains_secret(content):
        raise MemoryPolicyViolation(
            "memory content looks like it contains a secret or credential"
        )

    for pattern in _INJECTION_PATTERNS:
        if pattern.search(content):
            raise MemoryPolicyViolation(
                "memory content looks like an injected instruction, not a verified fact"
            )


def check_profile_ownership(*, target_user_id: uuid.UUID, actor_user_id: uuid.UUID) -> None:
    """Profile memory can only ever be written for the user it's about —
    there's no legitimate path for setting someone else's preferences.
    """
    if target_user_id != actor_user_id:
        raise MemoryPolicyViolation("a user can only set their own profile memory")
