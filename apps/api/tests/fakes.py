from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.tools import BaseTool
from pydantic import BaseModel


class FakeAgentLLM:
    """Deterministic AgentLLM test double — no network call, fully scripted.

    `tool_call_script` is a queue of "what the model decides to call this
    turn": each entry is a list of ToolCall dicts (empty list means "no more
    tool calls, I'm done gathering"). Once the queue is empty, further calls
    return an empty-tool-calls AIMessage so a test doesn't have to script
    every turn exactly if it doesn't care about the tail.

    `structured_responses` is a schema-keyed queue of canned Pydantic
    instances to return from `call_structured`, in order.
    """

    def __init__(
        self,
        *,
        tool_call_script: list[list[dict]] | None = None,
        structured_responses: dict[type, list[BaseModel]] | None = None,
    ) -> None:
        self._tool_call_script = list(tool_call_script or [])
        self._structured_responses = {k: list(v) for k, v in (structured_responses or {}).items()}
        self.call_with_tools_count = 0
        self.call_structured_count = 0

    async def call_with_tools(
        self, messages: list[BaseMessage], tools: list[BaseTool]
    ) -> AIMessage:
        self.call_with_tools_count += 1
        calls = self._tool_call_script.pop(0) if self._tool_call_script else []
        if calls:
            return AIMessage(content="", tool_calls=calls)
        return AIMessage(content="I have enough evidence to proceed.")

    async def call_structured(self, messages: list[BaseMessage], schema: type) -> BaseModel:
        self.call_structured_count += 1
        queue = self._structured_responses.get(schema)
        if not queue:
            raise AssertionError(f"FakeAgentLLM: no scripted response left for {schema.__name__}")
        return queue.pop(0)


def tool_call(name: str, args: dict, call_id: str) -> dict:
    return {"name": name, "args": args, "id": call_id, "type": "tool_call"}
