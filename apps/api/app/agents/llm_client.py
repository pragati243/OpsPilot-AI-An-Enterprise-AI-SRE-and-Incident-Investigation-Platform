from typing import Protocol, TypeVar

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.tools import BaseTool
from pydantic import BaseModel

from app.core.config import get_settings
from app.observability.client import get_langfuse_client
from app.observability.serialization import extract_usage_details, serialize_messages

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
    def __init__(self, chat_model: BaseChatModel, *, model_name: str) -> None:
        self._chat_model = chat_model
        self._model_name = model_name

    async def call_with_tools(
        self, messages: list[BaseMessage], tools: list[BaseTool]
    ) -> AIMessage:
        bound = self._chat_model.bind_tools(tools)
        with get_langfuse_client().start_as_current_observation(
            name="groq_call_with_tools",
            as_type="generation",
            model=self._model_name,
            input=serialize_messages(messages),
        ) as generation:
            result = await bound.ainvoke(messages)
            if not isinstance(result, AIMessage):
                raise TypeError(f"expected AIMessage from chat model, got {type(result)!r}")
            usage = extract_usage_details(result)
            generation.update(
                output=serialize_messages([result])[0],
                usage_details=usage,
            )
        return result

    async def call_structured(
        self, messages: list[BaseMessage], schema: type[SchemaT]
    ) -> SchemaT:
        structured = self._chat_model.with_structured_output(schema, include_raw=True)
        with get_langfuse_client().start_as_current_observation(
            name=f"groq_call_structured:{schema.__name__}",
            as_type="generation",
            model=self._model_name,
            input=serialize_messages(messages),
        ) as generation:
            raw_result = await structured.ainvoke(messages)
            if not isinstance(raw_result, dict):
                raise TypeError(
                    f"expected a dict from with_structured_output(include_raw=True), "
                    f"got {type(raw_result)!r}"
                )
            parsed = raw_result["parsed"]
            if not isinstance(parsed, schema):
                raise TypeError(
                    f"expected {schema.__name__} from structured output, got {type(parsed)!r}"
                )
            raw_message = raw_result.get("raw")
            usage = extract_usage_details(raw_message) if raw_message is not None else None
            generation.update(
                output=parsed.model_dump(mode="json"),
                usage_details=usage,
            )
        return parsed


class LLMNotConfiguredError(Exception):
    """Raised instead of letting the OpenAI SDK's generic 'Missing
    credentials' error surface — that one happens during FastAPI dependency
    resolution, before a route's own try/except ever runs, so it would
    otherwise reach the client as a bare 500 with an internal stack trace.
    """


def build_groq_llm() -> GroqAgentLLM:
    from langchain_openai import ChatOpenAI
    from pydantic import SecretStr

    settings = get_settings()
    if not settings.groq_api_key:
        raise LLMNotConfiguredError(
            "GROQ_API_KEY is not set — the investigation endpoints need it to call Groq."
        )
    chat_model = ChatOpenAI(
        model=settings.groq_model,
        api_key=SecretStr(settings.groq_api_key),
        base_url=settings.groq_base_url,
        timeout=30,
        max_retries=2,
    )
    return GroqAgentLLM(chat_model, model_name=settings.groq_model)
