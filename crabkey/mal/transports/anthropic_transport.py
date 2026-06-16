"""Anthropic Messages API transport.

Handles api_mode='anthropic_messages' — used by the native Anthropic SDK
(claude-* models) and Anthropic-compatible endpoints (MiniMax, etc.).

Ported from Hermes Agent's agent/transports/anthropic.py pattern.
"""

from __future__ import annotations

import json
from typing import Any

from ..transport import (
    NormalizedResponse,
    NormalizedToolCall,
    NormalizedUsage,
    ProviderTransport,
    register_transport,
)


class AnthropicMessagesTransport(ProviderTransport):
    """Transport for api_mode='anthropic_messages'."""

    @property
    def api_mode(self) -> str:
        return "anthropic_messages"

    def convert_messages(
        self, messages: list[dict[str, Any]], **kwargs
    ) -> tuple[str | None, list[dict[str, Any]]]:
        """Split OpenAI-format messages into (system_prompt, anthropic_messages).

        Returns (system_text_or_none, messages_without_system).
        """
        system = None
        converted = []
        for msg in messages:
            role = msg.get("role")
            if role == "system":
                system = msg.get("content") or ""
                continue
            if role == "tool":
                # Tool results — convert to Anthropic user message with tool_result content
                content = [
                    {
                        "type": "tool_result",
                        "tool_use_id": msg.get("tool_call_id", ""),
                        "content": msg.get("content", ""),
                    }
                ]
                converted.append({"role": "user", "content": content})
            elif msg.get("tool_calls"):
                # Assistant with tool calls
                content: list[dict[str, Any]] = []
                if msg.get("content"):
                    content.append({"type": "text", "text": msg["content"]})
                for tc in msg["tool_calls"]:
                    fn = tc.get("function", tc)
                    args = fn.get("arguments", "{}")
                    try:
                        args_dict = json.loads(args) if isinstance(args, str) else args
                    except json.JSONDecodeError:
                        args_dict = {}
                    content.append({
                        "type": "tool_use",
                        "id": tc.get("id", ""),
                        "name": fn.get("name", ""),
                        "input": args_dict,
                    })
                converted.append({"role": "assistant", "content": content})
            else:
                converted.append({"role": role, "content": msg.get("content", "")})
        return system, converted

    def convert_tools(self, tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Convert OpenAI tool format to Anthropic input_schema format."""
        anthropic_tools = []
        for t in tools:
            fn = t.get("function", t)
            anthropic_tools.append({
                "name": fn.get("name", t.get("name", "")),
                "description": fn.get("description", t.get("description", "")),
                "input_schema": fn.get("parameters", t.get("parameters", {"type": "object", "properties": {}})),
            })
        return anthropic_tools

    def build_kwargs(
        self,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        **params: Any,
    ) -> dict[str, Any]:
        profile = params.get("provider_profile")

        # Run provider-specific message preprocessing if a profile is present.
        if profile is not None:
            messages = profile.prepare_messages(messages)

        system, anthropic_messages = self.convert_messages(messages)

        # max_tokens: ephemeral > user-set > profile default > hard minimum
        max_tokens = (
            params.get("ephemeral_max_tokens")
            or params.get("max_tokens")
            or (profile.get_max_tokens(model) if profile else None)
            or 8192
        )

        api_kwargs: dict[str, Any] = {
            "model": model,
            "messages": anthropic_messages,
            "max_tokens": max_tokens,
        }
        if system:
            api_kwargs["system"] = system
        if tools:
            api_kwargs["tools"] = self.convert_tools(tools)
        if (temp := params.get("temperature")) is not None:
            api_kwargs["temperature"] = temp

        if profile is not None:
            # Provider-specific top-level extras (reasoning effort, metadata, etc.)
            extra_body_from_profile, top_level = profile.build_api_kwargs_extras(
                reasoning_config=params.get("reasoning_config"),
                supports_reasoning=params.get("supports_reasoning", False),
                model=model,
                session_id=params.get("session_id"),
            )
            api_kwargs.update(top_level)

            # Merge any extra_body additions into betas / system-level params.
            profile_body = profile.build_extra_body(
                session_id=params.get("session_id"),
                model=model,
                reasoning_config=params.get("reasoning_config"),
            )
            if profile_body:
                api_kwargs.setdefault("extra_body", {}).update(profile_body)
            if extra_body_from_profile:
                api_kwargs.setdefault("extra_body", {}).update(extra_body_from_profile)

        return api_kwargs

    def normalize_response(self, response: Any, **kwargs) -> NormalizedResponse:
        tool_calls = []
        text_parts: list[str] = []
        for block in response.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_calls.append(NormalizedToolCall(
                    id=block.id,
                    name=block.name,
                    arguments=json.dumps(block.input),
                ))
            elif block.type == "thinking":
                pass  # ignored for now

        usage = None
        if hasattr(response, "usage") and response.usage:
            u = response.usage
            usage = NormalizedUsage(
                prompt_tokens=getattr(u, "input_tokens", 0) or 0,
                completion_tokens=getattr(u, "output_tokens", 0) or 0,
                cached_tokens=getattr(u, "cache_read_input_tokens", 0) or 0,
            )

        finish_map = {
            "end_turn": "stop",
            "tool_use": "tool_calls",
            "max_tokens": "length",
        }
        finish = finish_map.get(response.stop_reason, response.stop_reason or "stop")

        return NormalizedResponse(
            content="\n".join(text_parts) or None,
            tool_calls=tool_calls or None,
            finish_reason=finish,
            usage=usage,
        )

    def validate_response(self, response: Any) -> bool:
        return bool(response and hasattr(response, "content"))


# Auto-register on import
register_transport("anthropic_messages", AnthropicMessagesTransport)
