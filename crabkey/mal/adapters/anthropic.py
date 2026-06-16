from __future__ import annotations

from typing import Any, AsyncIterator

from ..message import (
    CompletionResponse, Message, Role, ToolCall, ToolResult, Usage,
)
from ..provider import ModelConfig, ModelProvider, ToolSchema


class AnthropicAdapter(ModelProvider):
    """Adapter for the Anthropic Messages API (claude-* models)."""

    def __init__(self, api_key: str | None = None) -> None:
        try:
            import anthropic as sdk
        except ImportError as exc:
            raise ImportError("Install 'anthropic' to use AnthropicAdapter.") from exc
        self._client = sdk.AsyncAnthropic(api_key=api_key)

    @property
    def name(self) -> str:
        return "anthropic"

    def _to_sdk_messages(self, messages: list[Message]) -> list[dict[str, Any]]:
        result = []
        for m in messages:
            if m.role == Role.SYSTEM:
                continue  # system is a top-level param in Anthropic API
            if m.role == Role.TOOL:
                content = [
                    {
                        "type": "tool_result",
                        "tool_use_id": r.tool_call_id,
                        "content": r.content,
                        "is_error": r.is_error,
                    }
                    for r in m.tool_results
                ]
                result.append({"role": "user", "content": content})
            elif m.tool_calls:
                content: list[dict[str, Any]] = []
                if m.content:
                    content.append({"type": "text", "text": m.content})
                for tc in m.tool_calls:
                    content.append({"type": "tool_use", "id": tc.id, "name": tc.name, "input": tc.arguments})
                result.append({"role": "assistant", "content": content})
            else:
                result.append({"role": m.role.value, "content": m.content or ""})
        return result

    def _parse_response(self, resp: Any, model: str) -> CompletionResponse:
        tool_calls: list[ToolCall] = []
        text_parts: list[str] = []
        for block in resp.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_calls.append(ToolCall(id=block.id, name=block.name, arguments=block.input))
        msg = Message(
            role=Role.ASSISTANT,
            content="\n".join(text_parts) or None,
            tool_calls=tool_calls,
        )
        usage = Usage(
            input_tokens=resp.usage.input_tokens,
            output_tokens=resp.usage.output_tokens,
        )
        return CompletionResponse(message=msg, usage=usage, model=model, stop_reason=resp.stop_reason)

    def _system(self, messages: list[Message]) -> str | None:
        for m in messages:
            if m.role == Role.SYSTEM:
                return m.content
        return None

    async def complete(
        self,
        messages: list[Message],
        config: ModelConfig,
        tools: list[ToolSchema] | None = None,
    ) -> CompletionResponse:
        kwargs: dict[str, Any] = {
            "model": config.model,
            "max_tokens": config.max_tokens,
            "messages": self._to_sdk_messages(messages),
        }
        if system := self._system(messages):
            kwargs["system"] = system
        if tools:
            kwargs["tools"] = [
                {"name": t.name, "description": t.description, "input_schema": t.parameters}
                for t in tools
            ]
        resp = await self._client.messages.create(**kwargs)
        return self._parse_response(resp, config.model)

    async def stream(
        self,
        messages: list[Message],
        config: ModelConfig,
        tools: list[ToolSchema] | None = None,
    ) -> AsyncIterator[str]:
        kwargs: dict[str, Any] = {
            "model": config.model,
            "max_tokens": config.max_tokens,
            "messages": self._to_sdk_messages(messages),
        }
        if system := self._system(messages):
            kwargs["system"] = system
        async with self._client.messages.stream(**kwargs) as stream:
            async for text in stream.text_stream:
                yield text

    def count_tokens(self, messages: list[Message], config: ModelConfig) -> int:
        # Rough heuristic: 4 chars per token.
        total = sum(len(m.content or "") for m in messages)
        return total // 4
