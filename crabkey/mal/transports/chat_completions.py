"""OpenAI Chat Completions transport.

Handles api_mode='chat_completions' — used by OpenRouter, DeepSeek, xAI,
Mistral, Groq, NVIDIA, local models (Ollama, LM Studio, llama.cpp), and
any other OpenAI-compatible endpoint.

Messages and tools are already in OpenAI format, so convert_messages and
convert_tools are near-identity.  Complexity lives in build_kwargs which
handles provider-specific max_tokens, reasoning config, and extra_body.

Ported from Hermes Agent's agent/transports/chat_completions.py.
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


class ChatCompletionsTransport(ProviderTransport):
    """Transport for api_mode='chat_completions'."""

    @property
    def api_mode(self) -> str:
        return "chat_completions"

    def convert_messages(
        self, messages: list[dict[str, Any]], **kwargs
    ) -> list[dict[str, Any]]:
        """Strip CrabKey-internal fields that strict providers reject."""
        needs_strip = False
        for msg in messages:
            if not isinstance(msg, dict):
                continue
            if any(k.startswith("_") for k in msg if isinstance(k, str)):
                needs_strip = True
                break
            if "tool_name" in msg:
                needs_strip = True
                break

        if not needs_strip:
            return messages

        import copy
        cleaned = copy.deepcopy(messages)
        for msg in cleaned:
            if not isinstance(msg, dict):
                continue
            for k in [k for k in msg if isinstance(k, str) and k.startswith("_")]:
                msg.pop(k, None)
            msg.pop("tool_name", None)
        return cleaned

    def convert_tools(self, tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return tools  # already in OpenAI format

    def build_kwargs(
        self,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        **params: Any,
    ) -> dict[str, Any]:
        sanitized = self.convert_messages(messages, model=model)

        profile = params.get("provider_profile")
        if profile is not None:
            return self._build_from_profile(profile, model, sanitized, tools, params)

        # Generic fallback for unregistered providers
        api_kwargs: dict[str, Any] = {"model": model, "messages": sanitized}
        if timeout := params.get("timeout"):
            api_kwargs["timeout"] = timeout
        if tools:
            api_kwargs["tools"] = self.convert_tools(tools)
        if (max_tokens := params.get("max_tokens")) is not None:
            api_kwargs["max_tokens"] = max_tokens
        if (temp := params.get("temperature")) is not None:
            api_kwargs["temperature"] = temp
        return api_kwargs

    def _build_from_profile(
        self, profile: Any, model: str, messages: list, tools: list | None, params: dict
    ) -> dict[str, Any]:
        from ..profile import OMIT_TEMPERATURE

        messages = profile.prepare_messages(messages)

        api_kwargs: dict[str, Any] = {"model": model, "messages": messages}

        # Temperature
        if profile.fixed_temperature is OMIT_TEMPERATURE:
            pass
        elif profile.fixed_temperature is not None:
            api_kwargs["temperature"] = profile.fixed_temperature
        elif (temp := params.get("temperature")) is not None:
            api_kwargs["temperature"] = temp

        if (timeout := params.get("timeout")) is not None:
            api_kwargs["timeout"] = timeout

        if tools:
            api_kwargs["tools"] = self.convert_tools(tools)

        # max_tokens: ephemeral > user-set > profile default
        profile_max = profile.get_max_tokens(model)
        for key in ("ephemeral_max_tokens", "max_tokens"):
            val = params.get(key)
            if val is not None:
                api_kwargs["max_tokens"] = val
                break
        else:
            if profile_max is not None:
                api_kwargs["max_tokens"] = profile_max

        # Provider-specific api_kwargs extras (reasoning_effort, metadata, etc.)
        extra_body_from_profile, top_level = profile.build_api_kwargs_extras(
            reasoning_config=params.get("reasoning_config"),
            supports_reasoning=params.get("supports_reasoning", False),
            model=model,
            base_url=params.get("base_url") or profile.base_url,
            session_id=params.get("session_id"),
        )
        api_kwargs.update(top_level)

        # extra_body
        extra_body: dict[str, Any] = {}
        profile_body = profile.build_extra_body(
            session_id=params.get("session_id"),
            model=model,
            base_url=params.get("base_url") or profile.base_url,
            reasoning_config=params.get("reasoning_config"),
        )
        if profile_body:
            extra_body.update(profile_body)
        if extra_body_from_profile:
            extra_body.update(extra_body_from_profile)

        if extra_body:
            api_kwargs["extra_body"] = extra_body

        return api_kwargs

    def normalize_response(self, response: Any, **kwargs) -> NormalizedResponse:
        choice = response.choices[0]
        msg = choice.message
        finish_reason = choice.finish_reason or "stop"

        tool_calls = None
        if msg.tool_calls:
            tool_calls = [
                NormalizedToolCall(
                    id=tc.id,
                    name=tc.function.name,
                    arguments=tc.function.arguments,
                )
                for tc in msg.tool_calls
            ]

        usage = None
        if hasattr(response, "usage") and response.usage:
            u = response.usage
            usage = NormalizedUsage(
                prompt_tokens=getattr(u, "prompt_tokens", 0) or 0,
                completion_tokens=getattr(u, "completion_tokens", 0) or 0,
                total_tokens=getattr(u, "total_tokens", 0) or 0,
            )

        provider_data: dict[str, Any] = {}
        reasoning_content = getattr(msg, "reasoning_content", None)
        if reasoning_content:
            provider_data["reasoning_content"] = reasoning_content

        content = msg.content
        return NormalizedResponse(
            content=content,
            tool_calls=tool_calls,
            finish_reason=finish_reason,
            usage=usage,
            provider_data=provider_data or None,
        )

    def validate_response(self, response: Any) -> bool:
        return bool(
            response is not None
            and hasattr(response, "choices")
            and response.choices
        )

    def extract_cache_stats(self, response: Any) -> dict[str, int] | None:
        usage = getattr(response, "usage", None)
        if not usage:
            return None
        details = getattr(usage, "prompt_tokens_details", None)
        if not details:
            return None
        cached = getattr(details, "cached_tokens", 0) or 0
        if cached:
            return {"cached_tokens": cached, "creation_tokens": 0}
        return None


# Auto-register on import
register_transport("chat_completions", ChatCompletionsTransport)
