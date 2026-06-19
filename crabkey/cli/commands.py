"""Custom slash commands loaded from TOML files.

A command file (e.g. .crabkey/commands/review.toml) looks like:

    description = "Review the staged diff"
    prompt = "Review this diff for bugs:\\n{{args}}"

`{{args}}` is replaced with whatever the user typed after the command; if the
template has no `{{args}}` placeholder, the args are appended. The command name
defaults to the file stem but may be overridden with a `name` field.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib


@dataclass
class CustomCommand:
    name: str
    description: str
    prompt: str


def expand(template: str, args: str) -> str:
    """Substitute user args into a command template."""
    if "{{args}}" in template:
        return template.replace("{{args}}", args)
    if args:
        return f"{template}\n\n{args}"
    return template


def load_custom_commands(dirs: list[Path]) -> dict[str, CustomCommand]:
    """Load command definitions from each directory.

    Directories are processed in order, so later ones override earlier ones
    (e.g. project commands override extension/global commands of the same name).
    """
    commands: dict[str, CustomCommand] = {}
    for directory in dirs:
        directory = Path(directory).expanduser()
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("*.toml")):
            try:
                data = tomllib.loads(path.read_text(encoding="utf-8"))
            except (OSError, tomllib.TOMLDecodeError):
                continue
            prompt = data.get("prompt")
            if not prompt:
                continue  # a command without a prompt is meaningless
            name = data.get("name", path.stem)
            commands[name] = CustomCommand(
                name=name,
                description=data.get("description", ""),
                prompt=prompt,
            )
    return commands
