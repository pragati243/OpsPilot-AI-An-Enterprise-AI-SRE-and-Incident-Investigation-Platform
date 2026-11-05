from app.core.redaction import contains_secret, redact_secrets, truncate
from app.observability.client import get_langfuse_client
from app.observability.masking import mask_data


def test_contains_secret_detects_api_key() -> None:
    assert contains_secret("api_key: sk-abcdefghij1234567890klmnop")


def test_contains_secret_false_for_ordinary_text() -> None:
    assert not contains_secret("checkout-service is degraded")


def test_redact_secrets_removes_the_secret_value() -> None:
    redacted = redact_secrets("my api_key: sk-abcdefghij1234567890klmnop is here")
    assert "sk-abcdefghij1234567890klmnop" not in redacted
    assert "[REDACTED]" in redacted


def test_truncate_leaves_short_strings_unchanged() -> None:
    assert truncate("short") == "short"


def test_truncate_bounds_long_strings() -> None:
    text = "x" * 5000
    result = truncate(text, max_length=100)
    assert len(result) < 5000
    assert result.startswith("x" * 100)
    assert "truncated" in result


def test_mask_data_redacts_secret_nested_in_a_dict() -> None:
    data = {"log": "connection failed, api_key: sk-abcdefghij1234567890klmnop retrying"}
    masked = mask_data(data=data)
    assert "sk-abcdefghij1234567890klmnop" not in str(masked)


def test_mask_data_blanks_sensitive_key_names_outright() -> None:
    data = {"Authorization": "Bearer some-real-token-value", "service": "checkout-service"}
    masked = mask_data(data=data)
    assert masked["Authorization"] == "[REDACTED]"
    assert masked["service"] == "checkout-service"


def test_mask_data_truncates_long_string_values() -> None:
    data = {"raw_log_dump": "x" * 5000}
    masked = mask_data(data=data)
    assert len(masked["raw_log_dump"]) < 5000


def test_mask_data_recurses_into_lists() -> None:
    data = ["normal entry", "api_key: sk-abcdefghij1234567890klmnop"]
    masked = mask_data(data=data)
    assert "sk-abcdefghij1234567890klmnop" not in str(masked)


def test_langfuse_spans_are_inert_when_no_keys_configured() -> None:
    """conftest.py blanks LANGFUSE_* for the whole test session. This is
    deliberately NOT a test of `auth_check()` — that method always makes a
    real network call to validate credentials regardless of whether tracing
    is enabled, which is exactly the kind of network dependency a test
    suite must never have. What actually matters is the call pattern used
    everywhere in the agent graph (start_as_current_observation + update);
    that has to complete silently with no credentials, never raise.
    """
    client = get_langfuse_client()
    assert client._tracing_enabled is False

    with client.start_as_current_observation(name="test_span", as_type="span") as span:
        span.update(output={"ok": True})
