"""Recording variant of apps/api/tests/fakes.py::FakeAgentLLM — same
scripted-response contract (no network call, fully deterministic), but
this one also records every call's input messages. Evaluators need that to
assert on what the agent nodes actually *built and sent* to the model —
e.g. that a recalled memory or an injected incident title really reached a
prompt — not just on the final report, which a bug upstream of the model
call could still produce by coincidence.

No `app.*` import here, so no sys.path bootstrap: langchain_core is a
plain project dependency, resolvable from anywhere without apps/api on the
path.
"""

from typing import TypeVar, cast

from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.tools import BaseTool
from pydantic import BaseModel

SchemaT = TypeVar("SchemaT", bound=BaseModel)


class RecordingFakeAgentLLM:
    def __init__(
        self,
        *,
        tool_call_script: list[list[dict]] | None = None,
        structured_responses: dict[type, list[BaseModel]] | None = None,
    ) -> None:
        self._tool_call_script = list(tool_call_script or [])
        self._structured_responses = {
            schema: list(responses) for schema, responses in (structured_responses or {}).items()
        }
        self.call_with_tools_history: list[list[BaseMessage]] = []
        self.call_structured_history: list[tuple[list[BaseMessage], type]] = []

    async def call_with_tools(
        self, messages: list[BaseMessage], tools: list[BaseTool]
    ) -> AIMessage:
        self.call_with_tools_history.append(list(messages))
        calls = self._tool_call_script.pop(0) if self._tool_call_script else []
        if calls:
            return AIMessage(content="", tool_calls=calls)
        return AIMessage(content="I have enough evidence to proceed.")

    async def call_structured(
        self, messages: list[BaseMessage], schema: type[SchemaT]
    ) -> SchemaT:
        self.call_structured_history.append((list(messages), schema))
        queue = self._structured_responses.get(schema)
        if not queue:
            raise AssertionError(
                f"RecordingFakeAgentLLM: no scripted response left for {schema.__name__}"
            )
        return cast(SchemaT, queue.pop(0))

    def prompt_text_for(self, schema: type) -> str:
        """Concatenated content of every message sent to `call_structured`
        for `schema`, across all calls to it — the simplest surface for a
        substring check like "did the recalled memory's text reach here".
        """
        return "\n".join(
            str(message.content)
            for messages, recorded_schema in self.call_structured_history
            if recorded_schema is schema
            for message in messages
        )

    def tool_prompt_text(self) -> str:
        """Same idea for `call_with_tools` — the gather loop's own prompt."""
        return "\n".join(
            str(message.content)
            for messages in self.call_with_tools_history
            for message in messages
        )


def tool_call(name: str, args: dict, call_id: str) -> dict:
    return {"name": name, "args": args, "id": call_id, "type": "tool_call"}
