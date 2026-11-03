from typing import Protocol, TypeVar

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.tools import BaseTool
from pydantic import BaseModel

from app.core.config import get_settings

SchemaT = TypeVar("SchemaT", bound=BaseModel)


class AgentLLM(Protocol):
    """Narrow seam between graph nodes and the LLM. Production code
    implements this over a real LangChain chat model; tests implement it
    with scripted, deterministic responses — no graph node ever imports
    LangChain's model classes directly, so swapping one for the other is
    just passing a different object in.
    """

    async def call_with_tools(
        self, messages: list[BaseMessage], tools: list[BaseTool]
    ) -> AIMessage: ...

    async def call_structured(
        self, messages: list[BaseMessage], schema: type[SchemaT]
    ) -> SchemaT: ...


class GroqAgentLLM:
    def __init__(self, chat_model: BaseChatModel) -> None:
        self._chat_model = chat_model

    async def call_with_tools(
        self, messages: list[BaseMessage], tools: list[BaseTool]
    ) -> AIMessage:
        bound = self._chat_model.bind_tools(tools)
        result = await bound.ainvoke(messages)
        if not isinstance(result, AIMessage):
            raise TypeError(f"expected AIMessage from chat model, got {type(result)!r}")
        return result

    async def call_structured(
        self, messages: list[BaseMessage], schema: type[SchemaT]
    ) -> SchemaT:
        structured = self._chat_model.with_structured_output(schema)
        result = await structured.ainvoke(messages)
        if not isinstance(result, schema):
            raise TypeError(
                f"expected {schema.__name__} from structured output, got {type(result)!r}"
            )
        return result


def build_groq_llm() -> GroqAgentLLM:
    from langchain_openai import ChatOpenAI
    from pydantic import SecretStr

    settings = get_settings()
    chat_model = ChatOpenAI(
        model=settings.groq_model,
        api_key=SecretStr(settings.groq_api_key),
        base_url=settings.groq_base_url,
        timeout=30,
        max_retries=2,
    )
    return GroqAgentLLM(chat_model)
