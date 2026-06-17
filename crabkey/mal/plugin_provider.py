"""PluginModelProvider — concrete ModelProvider that uses ProviderProfile + ProviderTransport.

This replaces the per-adapter classes (AnthropicAdapter, OpenAIAdapter, etc.)
with a single class that reads configuration from a ProviderProfile and routes
wire-format conversion through the appropriate ProviderTransport.

Usage:
    from crabkey.mal.provider_registry import get_provider_profile
    from crabkey.mal.plugin_provider import PluginModelProvider

    profile = get_provider_profile("anthropic")
    provider = PluginModelProvider(profile, api_key="sk-...")
    response = await provider.complete(messages, ModelConfig(model="claude-sonnet-4-6"))
"""

from __future__ import annotations

import json
import os
from typing import Any, AsyncIterator

from .message import CompletionResponse, Message, Role, ToolCall, ToolResult, Usage
from .profile import ProviderProfile
from .provider import ModelConfig, ModelProvider, ToolSchema
from .transport import NormalizedResponse, get_transport


def _resolve_api_key(profile: ProviderProfile, override: str | None = None) -> str | None:
    if override:
        return override
    for var in profile.env_vars:
        val = os.environ.get(var)
        if val:
            return val
    return None


def _key_env_var(profile: ProviderProfile) -> str | None:
    """Return the first env var that looks like an API key (not a URL), or None."""
    for var in profile.env_vars:
        upper = var.upper()
        if "API_KEY" in upper or upper.endswith("_TOKEN") or upper.endswith("_SECRET"):
            return var
    return None


def _normalized_to_completion(resp: NormalizedResponse, model: str) -> CompletionResponse:
    """Convert NormalizedResponse (transport layer) → CompletionResponse (public API)."""
    tool_calls = []
    if resp.tool_calls:
        for tc in resp.tool_calls:
            args = tc.arguments
            try:
                args_dict = json.loads(args) if isinstance(args, str) else args
            except json.JSONDecodeError:
                args_dict = {}
            tool_calls.append(ToolCall(id=tc.id or "", name=tc.name, arguments=args_dict))

    msg = Message(
        role=Role.ASSISTANT,
        content=resp.content,
        tool_calls=tool_calls,
    )

    usage = Usage()
    if resp.usage:
        usage = Usage(
            input_tokens=resp.usage.prompt_tokens,
            output_tokens=resp.usage.completion_tokens,
            cache_read_tokens=resp.usage.cached_tokens,
        )

    stop_reason_map = {
        "stop": "end_turn",
        "tool_calls": "tool_use",
        "length": "max_tokens",
        "content_filter": "refusal",
    }

    return CompletionResponse(
        message=msg,
        usage=usage,
        model=model,
        stop_reason=stop_reason_map.get(resp.finish_reason, resp.finish_reason),
    )


def _messages_to_openai_wire(messages: list[Message]) -> list[dict[str, Any]]:
    """Convert internal Message objects to OpenAI-format wire dicts."""
    wire = []
    for m in messages:
        if m.role == Role.TOOL:
            for r in m.tool_results:
                wire.append({
                    "role": "tool",
                    "tool_call_id": r.tool_call_id,
                    "tool_name": r.name,
                    "content": r.content,
                })
        elif m.tool_calls:
            content_parts: list[dict] = []
            if m.content:
                content_parts.append({"type": "text", "text": m.content})
            tool_call_objs = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)},
                }
                for tc in m.tool_calls
            ]
            wire.append({
                "role": m.role.value,
                "content": m.content or "",
                "tool_calls": tool_call_objs,
            })
        else:
            wire.append({"role": m.role.value, "content": m.content or ""})
    return wire


class PluginModelProvider(ModelProvider):
    """Concrete ModelProvider backed by a ProviderProfile + ProviderTransport."""

    def __init__(
        self,
        profile: ProviderProfile,
        api_key: str | None = None,
    ) -> None:
        self._profile = profile
        self._api_key = _resolve_api_key(profile, api_key)
        self._transport = get_transport(profile.api_mode)
        self._client: Any = None

    def missing_key(self) -> str | None:
        """Return the env var name if a required API key is missing, else None."""
        var = _key_env_var(self._profile)
        if var is None:
            return None  # provider doesn't need a key (e.g. local)
        return var if not os.environ.get(var) and not self._api_key else None

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client

        if self._profile.api_mode == "anthropic_messages":
            try:
                import anthropic
            except ImportError as exc:
                raise ImportError("Install 'anthropic' to use the Anthropic provider.") from exc
            self._client = anthropic.AsyncAnthropic(api_key=self._api_key or None)
        else:
            try:
                import openai
            except ImportError as exc:
                raise ImportError("Install 'openai' to use OpenAI-compatible providers.") from exc

            # For providers that require a key, raise early with a clear message
            # rather than passing a literal "no-key" and getting a cryptic 401.
            key = self._api_key
            if key is None:
                var = _key_env_var(self._profile)
                if var:
                    raise RuntimeError(
                        f"No API key found for provider '{self._profile.name}'. "
                        f"Set the {var} environment variable, or run 'crabkey configure'."
                    )

            self._client = openai.AsyncOpenAI(
                api_key=key or "no-key",   # "no-key" only reached for keyless local servers
                base_url=self._profile.get_base_url() or None,
            )
        return self._client

    @property
    def name(self) -> str:
        return self._profile.name

    @property
    def profile(self) -> ProviderProfile:
        return self._profile

    def _tool_schemas_to_wire(
        self, tools: list[ToolSchema] | None
    ) -> list[dict[str, Any]] | None:
        if not tools:
            return None
        return [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters,
                },
            }
            for t in tools
        ]

    def _base_params(self, config: ModelConfig, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        """Build the common params dict passed to every transport.build_kwargs() call."""
        params: dict[str, Any] = {
            "provider_profile": self._profile,
            "max_tokens": config.max_tokens,
            "temperature": config.temperature,
            "base_url": self._profile.get_base_url(),
        }
        if extra:
            params.update(extra)
        return params

    async def complete(
        self,
        messages: list[Message],
        config: ModelConfig,
        tools: list[ToolSchema] | None = None,
        *,
        provider_preferences: dict[str, Any] | None = None,
        reasoning_config: dict[str, Any] | None = None,
        session_id: str | None = None,
    ) -> CompletionResponse:
        client = self._get_client()
        wire_messages = _messages_to_openai_wire(messages)
        wire_tools = self._tool_schemas_to_wire(tools)

        params = self._base_params(config, {
            "provider_preferences": provider_preferences,
            "reasoning_config": reasoning_config,
            "session_id": session_id,
        })
        kwargs = self._transport.build_kwargs(
            model=config.model,
            messages=wire_messages,
            tools=wire_tools,
            **params,
        )

        if self._profile.api_mode == "anthropic_messages":
            raw = await client.messages.create(**kwargs)
        else:
            raw = await client.chat.completions.create(**kwargs)

        normalized = self._transport.normalize_response(raw)
        return _normalized_to_completion(normalized, config.model)

    async def stream(
        self,
        messages: list[Message],
        config: ModelConfig,
        tools: list[ToolSchema] | None = None,
        *,
        provider_preferences: dict[str, Any] | None = None,
        reasoning_config: dict[str, Any] | None = None,
        session_id: str | None = None,
    ) -> AsyncIterator[str]:
        client = self._get_client()
        wire_messages = _messages_to_openai_wire(messages)

        params = self._base_params(config, {
            "provider_preferences": provider_preferences,
            "reasoning_config": reasoning_config,
            "session_id": session_id,
        })
        kwargs = self._transport.build_kwargs(
            model=config.model,
            messages=wire_messages,
            **params,
        )

        if self._profile.api_mode == "anthropic_messages":
            async with client.messages.stream(**kwargs) as stream_ctx:
                async for text in stream_ctx.text_stream:
                    yield text
        else:
            kwargs["stream"] = True
            async for chunk in await client.chat.completions.create(**kwargs):
                delta = chunk.choices[0].delta.content if chunk.choices else None
                if delta:
                    yield delta

    def count_tokens(self, messages: list[Message], config: ModelConfig) -> int:
        total = sum(len(m.content or "") for m in messages)
        return total // 4

    @classmethod
    def from_name(cls, provider_name: str, api_key: str | None = None) -> "PluginModelProvider":
        """Create a PluginModelProvider by looking up the named provider profile."""
        from .provider_registry import get_provider_profile
        profile = get_provider_profile(provider_name)
        if profile is None:
            raise KeyError(
                f"Unknown provider {provider_name!r}. "
                "Run list_providers() to see available providers, or add a plugin."
            )
        return cls(profile, api_key=api_key)
