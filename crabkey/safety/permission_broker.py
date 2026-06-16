from __future__ import annotations

import enum
from dataclasses import dataclass, field


class PermissionLevel(enum.Enum):
    ALLOW = "allow"
    DENY = "deny"
    ASK = "ask"


@dataclass
class Permission:
    tool: str
    level: PermissionLevel
    pattern: str | None = None  # optional glob/regex for path/command scoping


class PermissionBroker:
    """Decides whether a tool invocation is permitted before it executes."""

    def __init__(self) -> None:
        self._rules: list[Permission] = []

    def add_rule(self, rule: Permission) -> None:
        self._rules.append(rule)

    def check(self, tool: str, arg: str | None = None) -> PermissionLevel:
        import fnmatch

        for rule in reversed(self._rules):
            if rule.tool != tool and rule.tool != "*":
                continue
            if rule.pattern is None or arg is None:
                return rule.level
            if fnmatch.fnmatch(arg, rule.pattern):
                return rule.level
        return PermissionLevel.ASK

    def require(self, tool: str, arg: str | None = None) -> None:
        level = self.check(tool, arg)
        if level == PermissionLevel.DENY:
            raise PermissionError(f"Tool '{tool}' denied by permission policy (arg={arg!r})")
        if level == PermissionLevel.ASK:
            # In a real CLI this prompts the user; here we raise for now.
            raise PermissionError(
                f"Tool '{tool}' requires user confirmation (arg={arg!r}). "
                "Grant permission with broker.add_rule()."
            )
