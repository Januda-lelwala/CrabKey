"""Provider transport registry.

A transport owns the data path for one api_mode:
  convert_messages → convert_tools → build_kwargs → normalize_response

It does NOT own: client construction, streaming, retries, or auth.
Those stay on PluginModelProvider.

Ported from Hermes Agent's agent/transports/base.py pattern.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from .message import CompletionResponse, Message, ToolCall

# ── Transport registry ────────────────────────────────────────────────────────

_TRANSPORT_REGISTRY: dict[str, type["ProviderTransport"]] = {}


def register_transport(api_mode: str, cls: type["ProviderTransport"]) -> None:
    _TRANSPORT_REGISTRY[api_mode] = cls


def get_transport(api_mode: str) -> "ProviderTransport":
    cls = _TRANSPORT_REGISTRY.get(api_mode)
    if cls is None:
        raise KeyError(
            f"No transport registered for api_mode={api_mode!r}. "
            f"Available: {list(_TRANSPORT_REGISTRY)}"
        )
    return cls()


def list_api_modes() -> list[str]:
    return list(_TRANSPORT_REGISTRY)


# ── Normalized response types ─────────────────────────────────────────────────

from dataclasses import dataclass, field


@dataclass
class NormalizedToolCall:
    id: str | None
    name: str
    arguments: str           # raw JSON string
    provider_data: dict[str, Any] | None = field(default=None, repr=False)


@dataclass
class NormalizedUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cached_tokens: int = 0


@dataclass
class NormalizedResponse:
    """Canonical response shape that every transport normalizes to."""

    content: str | None
    tool_calls: list[NormalizedToolCall] | None
    finish_reason: str           # "stop" | "tool_calls" | "length" | "content_filter"
    reasoning: str | None = None
    usage: NormalizedUsage | None = None
    provider_data: dict[str, Any] | None = field(default=None, repr=False)


# ── Base class ────────────────────────────────────────────────────────────────

class ProviderTransport(ABC):
    """Base class for provider-specific format conversion and normalization."""

    @property
    @abstractmethod
    def api_mode(self) -> str:
        """The api_mode string this transport handles."""
        ...

    @abstractmethod
    def convert_messages(self, messages: list[dict[str, Any]], **kwargs) -> Any:
        """Convert internal messages to provider-native wire format."""
        ...

    @abstractmethod
    def convert_tools(self, tools: list[dict[str, Any]]) -> Any:
        """Convert tool definitions to provider-native format."""
        ...

    @abstractmethod
    def build_kwargs(
        self,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        **params: Any,
    ) -> dict[str, Any]:
        """Build the complete API call kwargs dict."""
        ...

    @abstractmethod
    def normalize_response(self, response: Any, **kwargs) -> NormalizedResponse:
        """Normalize a raw provider response to NormalizedResponse."""
        ...

    def validate_response(self, response: Any) -> bool:
        return True

    def extract_cache_stats(self, response: Any) -> dict[str, int] | None:
        return None

    def map_finish_reason(self, raw: str) -> str:
        return raw
