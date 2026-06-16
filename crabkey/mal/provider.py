from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

from .message import CompletionResponse, Message, ToolCall


@dataclass
class ToolSchema:
    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema object


@dataclass
class ModelConfig:
    model: str
    max_tokens: int = 8192
    temperature: float = 1.0
    system: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


class ModelProvider(ABC):
    """The spine: everything above the MAL calls only this interface."""

    @property
    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    async def complete(
        self,
        messages: list[Message],
        config: ModelConfig,
        tools: list[ToolSchema] | None = None,
    ) -> CompletionResponse: ...

    @abstractmethod
    async def stream(
        self,
        messages: list[Message],
        config: ModelConfig,
        tools: list[ToolSchema] | None = None,
    ) -> AsyncIterator[str]:
        """Yield text deltas as they arrive."""
        ...

    @abstractmethod
    def count_tokens(self, messages: list[Message], config: ModelConfig) -> int:
        """Estimate token count without making a network call."""
        ...
