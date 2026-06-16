from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from ..mal.provider import ToolSchema


@dataclass
class ToolContext:
    """Runtime context passed to every tool invocation."""
    working_dir: str
    env: dict[str, str] = field(default_factory=dict)


class Tool(ABC):
    """Base class for all CrabKey tools."""

    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    @abstractmethod
    def description(self) -> str: ...

    @property
    @abstractmethod
    def parameters(self) -> dict[str, Any]:
        """JSON Schema for the tool's arguments."""
        ...

    def schema(self) -> ToolSchema:
        return ToolSchema(name=self.name, description=self.description, parameters=self.parameters)

    @abstractmethod
    async def run(self, arguments: dict[str, Any], ctx: ToolContext) -> str: ...


class ToolRegistry:
    """Central registry that maps tool names to their implementations."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool:
        try:
            return self._tools[name]
        except KeyError:
            raise KeyError(f"Unknown tool: {name!r}")

    def schemas(self) -> list[ToolSchema]:
        return [t.schema() for t in self._tools.values()]

    def __iter__(self):
        return iter(self._tools.values())
