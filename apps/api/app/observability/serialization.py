from typing import Any

from langchain_core.messages import BaseMessage

from app.core.redaction import truncate

# Generation spans show a preview of each message, not the full transcript
# — bounded size regardless of how much evidence/log text ended up in a
# ToolMessage. The global mask (app/observability/masking.py) still runs on
# top of this as a second pass.
_MAX_CONTENT_PREVIEW = 500


def serialize_message(message: BaseMessage) -> dict[str, Any]:
    content = message.content if isinstance(message.content, str) else str(message.content)
    data: dict[str, Any] = {
        "role": message.__class__.__name__,
        "content": truncate(content, _MAX_CONTENT_PREVIEW),
    }
    tool_calls = getattr(message, "tool_calls", None)
    if tool_calls:
        data["tool_calls"] = [
            {"name": call.get("name"), "args": call.get("args")} for call in tool_calls
        ]
    return data


def serialize_messages(messages: list[BaseMessage]) -> list[dict[str, Any]]:
    return [serialize_message(message) for message in messages]


def extract_usage_details(message: BaseMessage) -> dict[str, int] | None:
    usage = getattr(message, "usage_metadata", None)
    if not usage:
        return None
    return {
        "input": usage.get("input_tokens", 0),
        "output": usage.get("output_tokens", 0),
        "total": usage.get("total_tokens", 0),
    }
