"""Extension bundles: MCP servers + context + custom commands packaged together.

An extension lives in `.crabkey/extensions/<name>/` with a manifest
`crabkey-extension.toml`:

    name = "postgres"
    version = "0.1.0"
    context = "context.md"          # optional, relative to the extension dir
    commands = "commands"           # optional dir of *.toml commands (default)

    [[mcp_servers]]
    name = "postgres"
    command = "npx"
    args = ["-y", "@modelcontextprotocol/server-postgres"]

This mirrors Gemini CLI's extensions framework, letting teams standardise tools,
context, and commands across a project.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib


@dataclass
class Extension:
    name: str
    root: Path
    context_file: Path | None = None
    command_dir: Path | None = None
    mcp_servers: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class LoadedExtensions:
    extensions: list[Extension] = field(default_factory=list)

    @property
    def mcp_servers(self) -> list[dict[str, Any]]:
        servers: list[dict[str, Any]] = []
        for ext in self.extensions:
            servers.extend(ext.mcp_servers)
        return servers

    @property
    def context_files(self) -> list[Path]:
        return [e.context_file for e in self.extensions if e.context_file]

    @property
    def command_dirs(self) -> list[Path]:
        return [e.command_dir for e in self.extensions if e.command_dir]

    @property
    def names(self) -> list[str]:
        return [e.name for e in self.extensions]


def load_extensions(project_root: Path) -> LoadedExtensions:
    """Discover and parse all extensions under <project_root>/.crabkey/extensions/."""
    ext_root = project_root / ".crabkey" / "extensions"
    loaded = LoadedExtensions()
    if not ext_root.is_dir():
        return loaded

    for ext_dir in sorted(p for p in ext_root.iterdir() if p.is_dir()):
        manifest = ext_dir / "crabkey-extension.toml"
        if not manifest.is_file():
            continue
        try:
            data = tomllib.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError):
            continue

        ctx_rel = data.get("context")
        if ctx_rel:
            context_file = ext_dir / ctx_rel
        else:
            default_ctx = ext_dir / "context.md"
            context_file = default_ctx if default_ctx.is_file() else None

        cmd_rel = data.get("commands", "commands")
        cmd_dir = ext_dir / cmd_rel
        command_dir = cmd_dir if cmd_dir.is_dir() else None

        loaded.extensions.append(
            Extension(
                name=data.get("name", ext_dir.name),
                root=ext_dir,
                context_file=context_file if (context_file and context_file.is_file()) else None,
                command_dir=command_dir,
                mcp_servers=data.get("mcp_servers", []),
            )
        )
    return loaded
