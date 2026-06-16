"""Tests for the safety layer — PermissionBroker."""

import pytest

from crabkey.safety.permission_broker import Permission, PermissionBroker, PermissionLevel


class TestPermissionBrokerCheck:
    def setup_method(self):
        self.broker = PermissionBroker()

    def test_default_returns_ask(self):
        assert self.broker.check("shell", "/bin/ls") == PermissionLevel.ASK

    def test_explicit_allow_rule(self):
        self.broker.add_rule(Permission(tool="shell", level=PermissionLevel.ALLOW))
        assert self.broker.check("shell") == PermissionLevel.ALLOW

    def test_explicit_deny_rule(self):
        self.broker.add_rule(Permission(tool="shell", level=PermissionLevel.DENY))
        assert self.broker.check("shell") == PermissionLevel.DENY

    def test_wildcard_tool_matches_any(self):
        self.broker.add_rule(Permission(tool="*", level=PermissionLevel.ALLOW))
        assert self.broker.check("file_read") == PermissionLevel.ALLOW
        assert self.broker.check("shell") == PermissionLevel.ALLOW

    def test_later_rule_wins(self):
        self.broker.add_rule(Permission(tool="shell", level=PermissionLevel.ALLOW))
        self.broker.add_rule(Permission(tool="shell", level=PermissionLevel.DENY))
        assert self.broker.check("shell") == PermissionLevel.DENY

    def test_pattern_allow_matching_path(self):
        self.broker.add_rule(Permission(tool="file_read", level=PermissionLevel.ALLOW, pattern="/tmp/*"))
        assert self.broker.check("file_read", "/tmp/safe.txt") == PermissionLevel.ALLOW

    def test_pattern_deny_non_matching_path(self):
        # Pattern rule only matches specific paths; non-matching falls through to default (ASK)
        self.broker.add_rule(Permission(tool="file_read", level=PermissionLevel.ALLOW, pattern="/tmp/*"))
        assert self.broker.check("file_read", "/etc/passwd") == PermissionLevel.ASK

    def test_different_tool_unaffected(self):
        self.broker.add_rule(Permission(tool="shell", level=PermissionLevel.ALLOW))
        assert self.broker.check("file_read") == PermissionLevel.ASK

    def test_no_arg_rule_matches_with_or_without_arg(self):
        self.broker.add_rule(Permission(tool="web_fetch", level=PermissionLevel.ALLOW))
        assert self.broker.check("web_fetch") == PermissionLevel.ALLOW
        assert self.broker.check("web_fetch", "https://example.com") == PermissionLevel.ALLOW


class TestPermissionBrokerRequire:
    def setup_method(self):
        self.broker = PermissionBroker()

    def test_require_allow_does_not_raise(self):
        self.broker.add_rule(Permission(tool="shell", level=PermissionLevel.ALLOW))
        self.broker.require("shell")  # should not raise

    def test_require_deny_raises_permission_error(self):
        self.broker.add_rule(Permission(tool="shell", level=PermissionLevel.DENY))
        with pytest.raises(PermissionError, match="denied"):
            self.broker.require("shell")

    def test_require_ask_raises_permission_error(self):
        # Default is ASK — should raise asking for confirmation
        with pytest.raises(PermissionError, match="confirmation"):
            self.broker.require("unknown_tool")

    def test_require_includes_arg_in_error(self):
        self.broker.add_rule(Permission(tool="shell", level=PermissionLevel.DENY))
        with pytest.raises(PermissionError, match="/bin/rm"):
            self.broker.require("shell", "/bin/rm")
