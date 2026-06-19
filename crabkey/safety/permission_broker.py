from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Callable


class PermissionLevel(enum.Enum):
    ALLOW = "allow"
    DENY = "deny"
    ASK = "ask"


class ApprovalDecision(enum.Enum):
    """User's answer to an interactive approval prompt."""
    ALLOW_ONCE = "allow_once"        # permit this call only
    ALLOW_ALWAYS = "allow_always"    # permit this call and add a session ALLOW rule
    DENY = "deny"                    # reject this call


# Called when a tool resolves to ASK and an interactive approver is available.
# Receives the tool name and a representative argument (path/command), returns
# the user's decision.
Approver = Callable[[str, "str | None"], ApprovalDecision]


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

    def require(self, tool: str, arg: str | None = None, on_ask: Approver | None = None) -> None:
        level = self.check(tool, arg)
        if level == PermissionLevel.DENY:
            raise PermissionError(f"Tool '{tool}' denied by permission policy (arg={arg!r})")
        if level != PermissionLevel.ASK:
            return

        if on_ask is None:
            # No interactive approver wired — preserve the conservative default
            # of refusing rather than silently permitting.
            raise PermissionError(
                f"Tool '{tool}' requires user confirmation (arg={arg!r}). "
                "Grant permission with broker.add_rule()."
            )

        decision = on_ask(tool, arg)
        if decision == ApprovalDecision.DENY:
            raise PermissionError(f"Tool '{tool}' denied by user (arg={arg!r})")
        if decision == ApprovalDecision.ALLOW_ALWAYS:
            # Remember for the rest of the session so we stop asking for this tool.
            self.add_rule(Permission(tool=tool, level=PermissionLevel.ALLOW))
