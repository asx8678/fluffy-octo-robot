from code_muse.plugins.policy_engine.approval_flow_integration import (
    integrate_policy_check,
)
from code_muse.plugins.policy_engine.policy_toml_schema import Decision, ToolRule


class TestIntegratePolicyCheck:
    def test_allow_shell_returns_auto_approve(self) -> None:
        rules = [
            ToolRule(
                tool_name="agent_run_shell_command",
                decision=Decision.ALLOW,
                priority=100,
                description="Auto-approve tests",
            ),
        ]
        result = integrate_policy_check("agent_run_shell_command", "npm test", rules)
        assert result == {"auto_approve": True}

    def test_allow_non_shell_returns_none(self) -> None:
        rules = [
            ToolRule(
                tool_name="write_file",
                decision=Decision.ALLOW,
                priority=100,
            ),
        ]
        result = integrate_policy_check("write_file", None, rules)
        assert result is None

    def test_deny_shell_returns_blocked(self) -> None:
        rules = [
            ToolRule(
                tool_name="agent_run_shell_command",
                command_prefix="git push",
                decision=Decision.DENY,
                priority=100,
                description="Block force push to main",
            ),
        ]
        result = integrate_policy_check(
            "agent_run_shell_command", "git push origin main", rules
        )
        assert result is not None
        assert result.get("blocked") is True
        assert "Policy: Block force push to main" in result.get("error_message", "")

    def test_deny_non_shell_returns_blocked(self) -> None:
        rules = [
            ToolRule(
                tool_name="delete_file",
                decision=Decision.DENY,
                priority=100,
                description="No deletions",
            ),
        ]
        result = integrate_policy_check("delete_file", None, rules)
        assert result is not None
        assert result.get("blocked") is True
        assert "Policy: No deletions" in result.get("error_message", "")

    def test_deny_without_description(self) -> None:
        rules = [
            ToolRule(
                tool_name="dangerous_tool",
                decision=Decision.DENY,
                priority=100,
            ),
        ]
        result = integrate_policy_check("dangerous_tool", None, rules)
        assert result is not None
        assert result.get("blocked") is True
        assert result.get("error_message") == "🚫 Policy: blocked dangerous_tool"

    def test_ask_user_returns_none(self) -> None:
        rules = [
            ToolRule(
                tool_name="*",
                decision=Decision.ASK_USER,
                priority=0,
                description="Default: ask",
            ),
        ]
        result = integrate_policy_check("any_tool", "any command", rules)
        assert result is None

    def test_no_match_returns_none(self) -> None:
        rules: list[ToolRule] = []
        result = integrate_policy_check("unknown_tool", None, rules)
        assert result is None

    def test_shell_auto_approve_skips_confirmation(self) -> None:
        rules = [
            ToolRule(
                tool_name="agent_run_shell_command",
                command_prefix="pytest",
                decision=Decision.ALLOW,
                priority=50,
            ),
        ]
        result = integrate_policy_check("agent_run_shell_command", "pytest -x", rules)
        assert result == {"auto_approve": True}

    def test_shell_deny_overrides_auto_approve(self) -> None:
        rules = [
            ToolRule(
                tool_name="agent_run_shell_command",
                command_prefix="rm",
                decision=Decision.DENY,
                priority=100,
            ),
            ToolRule(
                tool_name="agent_run_shell_command",
                decision=Decision.ALLOW,
                priority=50,
            ),
        ]
        result = integrate_policy_check("agent_run_shell_command", "rm -rf /", rules)
        assert result is not None
        assert result.get("blocked") is True
