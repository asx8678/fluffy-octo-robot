"""OpenAI ChatModel with provider compatibility patches.

Extracted from model_factory.py.  Some OpenAI-compatible providers
don't support ``strict: true`` on tool schemas, or error on
``role='tool'`` messages.  This class patches those incompatibilities
by converting closures into explicit constructor parameters.
"""

import orjson
from pydantic_ai.models.openai import OpenAIChatModel


class CompatChatModel(OpenAIChatModel):
    """OpenAIChatModel with provider compatibility patches.

    Parameters
    ----------
    strip_strict_tools : bool
        If True, remove ``strict`` from tool definitions before sending.
    tool_results_as_user : bool
        If True, degrade ``role='tool'`` messages to ``role='user'``.
    flatten_tool_calls : bool
        If True, embed tool-call text in assistant content instead of
        sending ``tool_calls`` in assistant messages.
    """

    def __init__(
        self,
        *,
        strip_strict_tools: bool = False,
        tool_results_as_user: bool = False,
        flatten_tool_calls: bool = False,
        **kwargs,
    ):
        self._strip_strict_tools = strip_strict_tools
        self._tool_results_as_user = tool_results_as_user
        self._flatten_tool_calls = flatten_tool_calls
        super().__init__(**kwargs)

    def _map_tool_definition(self, f):  # type: ignore[override]
        tool_param = super()._map_tool_definition(f)
        if self._strip_strict_tools:
            tool_param["function"].pop("strict", None)
        return tool_param

    def _map_model_response(self, message):  # type: ignore[override]
        """Optionally flatten tool calls into assistant text.

        Some OpenAI-compatible providers accept tool calling in
        responses but error on tool call/result message wiring
        in subsequent requests. For these providers we avoid
        sending `tool_calls` in assistant messages at all and
        instead embed a human-readable representation in the
        assistant content.
        """
        if not self._flatten_tool_calls:
            return super()._map_model_response(message)

        import orjson as json
        from openai.types.chat import (
            ChatCompletionAssistantMessageParam,
        )
        from pydantic_ai.messages import TextPart, ToolCallPart

        chunks: list[str] = []
        for part in message.parts:
            if isinstance(part, TextPart):
                if part.content:
                    chunks.append(part.content)
            elif isinstance(part, ToolCallPart):
                args = part.args
                if isinstance(args, dict):
                    args_str = json.dumps(args, option=orjson.OPT_SORT_KEYS)
                else:
                    args_str = "" if args is None else str(args)
                chunks.append(
                    f"TOOL CALL ({part.tool_name}, id={part.tool_call_id}): {args_str}"
                )
            else:
                # Ignore other part kinds (thinking, builtin, etc.) for provider safety.
                continue

        content = "\n\n".join([c for c in chunks if c is not None])
        return ChatCompletionAssistantMessageParam(
            role="assistant",
            content=content or None,
        )

    async def _map_user_message(self, message):  # type: ignore[override]
        # Import locally to keep import-time cost down.
        from openai.types.chat import (
            ChatCompletionDeveloperMessageParam,
            ChatCompletionSystemMessageParam,
            ChatCompletionToolMessageParam,
            ChatCompletionUserMessageParam,
        )
        from pydantic_ai._utils import (
            guard_tool_call_id as _guard_tool_call_id,
        )
        from pydantic_ai.messages import (
            RetryPromptPart,
            SystemPromptPart,
            ToolReturnPart,
            UserPromptPart,
        )
        from pydantic_ai.profiles.openai import OpenAIModelProfile

        for part in message.parts:
            if isinstance(part, SystemPromptPart):
                system_prompt_role = OpenAIModelProfile.from_profile(
                    self.profile
                ).openai_system_prompt_role
                if system_prompt_role == "developer":
                    yield ChatCompletionDeveloperMessageParam(
                        role="developer", content=part.content
                    )
                elif system_prompt_role == "user":
                    yield ChatCompletionUserMessageParam(
                        role="user", content=part.content
                    )
                else:
                    yield ChatCompletionSystemMessageParam(
                        role="system", content=part.content
                    )
            elif isinstance(part, UserPromptPart):
                yield await super()._map_user_prompt(part)
            elif isinstance(part, ToolReturnPart):
                if self._tool_results_as_user:
                    yield ChatCompletionUserMessageParam(
                        role="user",
                        content=(
                            f"TOOL RESULT ({part.tool_name}, id={part.tool_call_id}):\n"
                            f"{part.model_response_str()}"
                        ),
                    )
                else:
                    yield ChatCompletionToolMessageParam(
                        role="tool",
                        tool_call_id=_guard_tool_call_id(t=part),
                        content=part.model_response_str(),
                    )
            elif isinstance(part, RetryPromptPart):
                if part.tool_name is None:
                    yield ChatCompletionUserMessageParam(
                        role="user", content=part.model_response()
                    )
                else:
                    if self._tool_results_as_user:
                        yield ChatCompletionUserMessageParam(
                            role="user",
                            content=(
                                f"TOOL RESULT ({part.tool_name}, id={part.tool_call_id}):\n"
                                f"{part.model_response()}"
                            ),
                        )
                    else:
                        yield ChatCompletionToolMessageParam(
                            role="tool",
                            tool_call_id=_guard_tool_call_id(t=part),
                            content=part.model_response(),
                        )
            else:
                raise TypeError(f"Unsupported request part type: {type(part).__name__}")
