import logging

import pytest

from code_muse.plugins.policy_engine.policy_evaluator import (
    evaluate_policy,
    evaluate_tool_policy,
)
from code_muse.plugins.policy_engine.policy_toml_schema import Decision, ToolRule


class TestEvaluatePolicy:
    def test_exact_match(self) -> None:
        rules = [
            ToolRule(
                tool_name="agent_run_shell_command",
                decision=Decision.ALLOW,
                priority=10,
            ),
        ]
        decision, matched = evaluate_policy("agent_run_shell_command", "ls", rules)
        assert decision == Decision.ALLOW
        assert matched is not None
        assert matched.priority == 10

    def test_wildcard_match(self) -> None:
        rules = [
            ToolRule(tool_name="*", decision=Decision.ASK_USER, priority=0),
        ]
        decision, matched = evaluate_policy("any_tool", "any command", rules)
        assert decision == Decision.ASK_USER
        assert matched is not None
        assert matched.tool_name == "*"

    def test_command_prefix_filtering(self) -> None:
        rules = [
            ToolRule(
                tool_name="agent_run_shell_command",
                command_prefix="git push",
                decision=Decision.DENY,
                priority=100,
            ),
            ToolRule(
                tool_name="agent_run_shell_command",
                decision=Decision.ALLOW,
                priority=50,
            ),
        ]
        # Command matches prefix
        dec, _ = evaluate_policy(
            "agent_run_shell_command", "git push origin main", rules
        )
        assert dec == Decision.DENY

        # Command does NOT match prefix — falls through to lower-priority rule
        dec, _ = evaluate_policy("agent_run_shell_command", "ls -la", rules)
        assert dec == Decision.ALLOW

    def test_command_prefix_with_none_command(self) -> None:
        rules = [
            ToolRule(
                tool_name="agent_run_shell_command",
                command_prefix="git",
                decision=Decision.DENY,
                priority=100,
            ),
        ]
        # When command is None, command_prefix rules should be skipped
        decision, matched = evaluate_policy("agent_run_shell_command", None, rules)
        assert decision == Decision.ALLOW
        assert matched is None

    def test_priority_resolution(self) -> None:
        rules = [
            ToolRule(tool_name="foo", decision=Decision.ALLOW, priority=5),
            ToolRule(tool_name="foo", decision=Decision.DENY, priority=10),
        ]
        decision, matched = evaluate_policy("foo", None, rules)
        assert decision == Decision.DENY
        assert matched is not None
        assert matched.priority == 10

    def test_priority_conflict_different_decisions_logs_warning(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        rules = [
            ToolRule(tool_name="foo", decision=Decision.ALLOW, priority=10),
            ToolRule(tool_name="foo", decision=Decision.DENY, priority=10),
        ]
        with caplog.at_level(logging.WARNING):
            decision, matched = evaluate_policy("foo", None, rules)
        assert decision == Decision.ALLOW  # first registered wins
        assert "Policy conflict" in caplog.text

    def test_no_match_default_allow(self) -> None:
        rules: list[ToolRule] = []
        decision, matched = evaluate_policy("unknown_tool", "unknown command", rules)
        assert decision == Decision.ALLOW
        assert matched is None

    def test_fnmatch_wildcards(self) -> None:
        rules = [
            ToolRule(tool_name="agent_run_*", decision=Decision.ALLOW, priority=10),
        ]
        decision, matched = evaluate_policy("agent_run_shell_command", "ls", rules)
        assert decision == Decision.ALLOW
        assert matched is not None

        decision, matched = evaluate_policy("other_tool", "ls", rules)
        assert decision == Decision.ALLOW
        assert matched is None


class TestEvaluateToolPolicy:
    def test_evaluate_tool_policy_no_command(self) -> None:
        rules = [
            ToolRule(tool_name="write_file", decision=Decision.DENY, priority=100),
        ]
        decision, matched = evaluate_tool_policy("write_file", rules)
        assert decision == Decision.DENY
        assert matched is not None

    def test_command_prefix_ignored_in_tool_policy(self) -> None:
        rules = [
            ToolRule(
                tool_name="agent_run_shell_command",
                command_prefix="git",
                decision=Decision.DENY,
                priority=100,
            ),
        ]
        # evaluate_tool_policy passes command=None, so prefix filter skips it
        decision, matched = evaluate_tool_policy("agent_run_shell_command", rules)
        assert decision == Decision.ALLOW
        assert matched is None
