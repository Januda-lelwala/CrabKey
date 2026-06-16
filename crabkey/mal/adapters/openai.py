from __future__ import annotations

import json
from typing import Any, AsyncIterator

from ..message import CompletionResponse, Message, Role, ToolCall, Usage
from ..provider import ModelConfig, ModelProvider, ToolSchema


class OpenAIAdapter(ModelProvider):
    """Adapter for the OpenAI Chat Completions API (gpt-* and compatible models)."""

    def __init__(self, api_key: str | None = None, base_url: str | None = None) -> None:
        try:
            import openai as sdk
        except ImportError as exc:
            raise ImportError("Install 'openai' to use OpenAIAdapter.") from exc
        self._client = sdk.AsyncOpenAI(api_key=api_key, base_url=base_url)

    @property
    def name(self) -> str:
        return "openai"

    def _to_sdk_messages(self, messages: list[Message]) -> list[dict[str, Any]]:
        result = []
        for m in messages:
            if m.role == Role.TOOL:
                for r in m.tool_results:
                    result.append({"role": "tool", "tool_call_id": r.tool_call_id, "content": r.content})
            elif m.tool_calls:
                result.append({
                    "role": "assistant",
                    "content": m.content or "",
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)},
                        }
                        for tc in m.tool_calls
                    ],
                })
            else:
                result.append({"role": m.role.value, "content": m.content or ""})
        return result

    def _parse_response(self, resp: Any, model: str) -> CompletionResponse:
        choice = resp.choices[0]
        cm = choice.message
        tool_calls = []
        if cm.tool_calls:
            for tc in cm.tool_calls:
                tool_calls.append(ToolCall(
                    id=tc.id,
                    name=tc.function.name,
                    arguments=json.loads(tc.function.arguments),
                ))
        from ..message import Message as Msg
        msg = Msg(role=Role.ASSISTANT, content=cm.content, tool_calls=tool_calls)
        usage = Usage(input_tokens=resp.usage.prompt_tokens, output_tokens=resp.usage.completion_tokens)
        return CompletionResponse(message=msg, usage=usage, model=model, stop_reason=choice.finish_reason)

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
        if tools:
            kwargs["tools"] = [
                {"type": "function", "function": {"name": t.name, "description": t.description, "parameters": t.parameters}}
                for t in tools
            ]
        resp = await self._client.chat.completions.create(**kwargs)
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
            "stream": True,
        }
        async for chunk in await self._client.chat.completions.create(**kwargs):
            delta = chunk.choices[0].delta.content if chunk.choices else None
            if delta:
                yield delta

    def count_tokens(self, messages: list[Message], config: ModelConfig) -> int:
        total = sum(len(m.content or "") for m in messages)
        return total // 4


class OpenRouterAdapter(OpenAIAdapter):
    """OpenRouter is OpenAI-compatible — just point at their base URL."""

    def __init__(self, api_key: str) -> None:
        super().__init__(api_key=api_key, base_url="https://openrouter.ai/api/v1")

    @property
    def name(self) -> str:
        return "openrouter"
