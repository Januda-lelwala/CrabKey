from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib  # type: ignore[no-reuse-def]


@dataclass
class AgentConfig:
    name: str
    model: str
    system: str | None = None
    tools: list[str] = field(default_factory=list)
    max_tokens: int = 8192
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class ProjectConfig:
    provider: str = "anthropic"
    model: str = "claude-sonnet-4-6"
    max_tokens: int = 8192
    agents: dict[str, AgentConfig] = field(default_factory=dict)
    mcp_servers: list[dict[str, Any]] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path) -> "ProjectConfig":
        if not path.exists():
            return cls()
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        agents = {
            name: AgentConfig(name=name, **cfg)
            for name, cfg in data.pop("agents", {}).items()
        }
        return cls(agents=agents, **{k: v for k, v in data.items() if k != "agents"})

    @classmethod
    def from_project_dir(cls, project_root: Path) -> "ProjectConfig":
        return cls.load(project_root / ".crabkey" / "config.toml")
