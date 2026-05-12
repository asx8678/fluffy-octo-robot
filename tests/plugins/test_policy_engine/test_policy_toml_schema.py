import logging
from pathlib import Path

import pytest

from code_muse.plugins.policy_engine.policy_toml_schema import (
    Decision,
    ToolRule,
    parse_policy_toml,
    validate_rules,
)


class TestParsePolicyTOML:
    def test_valid_single_rule(self, tmp_path: Path) -> None:
        path = tmp_path / "test.toml"
        path.write_text(
            "[[rule]]\n"
            'toolName = "agent_run_shell_command"\n'
            'decision = "deny"\n'
            "priority = 100\n"
            'description = "Block all shell commands"\n',
            encoding="utf-8",
        )
        rules = parse_policy_toml(path)
        assert len(rules) == 1
        assert rules[0].tool_name == "agent_run_shell_command"
        assert rules[0].decision == Decision.DENY
        assert rules[0].priority == 100
        assert rules[0].description == "Block all shell commands"
        assert rules[0].command_prefix is None

    def test_multiple_rules(self, tmp_path: Path) -> None:
        path = tmp_path / "test.toml"
        path.write_text(
            'schema_version = "1"\n\n'
            "[[rule]]\n"
            'toolName = "agent_run_shell_command"\n'
            'commandPrefix = "git push"\n'
            'decision = "deny"\n'
            "priority = 100\n"
            'description = "Block force push to main"\n\n'
            "[[rule]]\n"
            'toolName = "agent_run_shell_command"\n'
            'commandPrefix = "npm test"\n'
            'decision = "allow"\n'
            "priority = 50\n"
            'description = "Auto-approve test runs"\n\n'
            "[[rule]]\n"
            'toolName = "*"\n'
            'decision = "ask_user"\n'
            "priority = 0\n"
            'description = "Default: ask for everything"\n',
            encoding="utf-8",
        )
        rules = parse_policy_toml(path)
        assert len(rules) == 3
        assert rules[0].command_prefix == "git push"
        assert rules[1].decision == Decision.ALLOW
        assert rules[2].tool_name == "*"

    def test_wildcard_tool_name(self, tmp_path: Path) -> None:
        path = tmp_path / "wildcard.toml"
        path.write_text(
            '[[rule]]\ntoolName = "*"\ndecision = "ask_user"\n',
            encoding="utf-8",
        )
        rules = parse_policy_toml(path)
        assert len(rules) == 1
        assert rules[0].tool_name == "*"
        assert rules[0].decision == Decision.ASK_USER
        assert rules[0].priority == 0
        assert rules[0].description == ""

    def test_missing_tool_name(self, tmp_path: Path) -> None:
        path = tmp_path / "bad.toml"
        path.write_text(
            '[[rule]]\ndecision = "deny"\n',
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="missing or invalid 'toolName'"):
            parse_policy_toml(path)

    def test_missing_decision(self, tmp_path: Path) -> None:
        path = tmp_path / "bad.toml"
        path.write_text(
            '[[rule]]\ntoolName = "foo"\n',
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="missing or invalid 'decision'"):
            parse_policy_toml(path)

    def test_invalid_decision(self, tmp_path: Path) -> None:
        path = tmp_path / "bad.toml"
        path.write_text(
            '[[rule]]\ntoolName = "foo"\ndecision = "banana"\n',
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="invalid decision 'banana'"):
            parse_policy_toml(path)

    def test_empty_file(self, tmp_path: Path) -> None:
        path = tmp_path / "empty.toml"
        path.write_text("", encoding="utf-8")
        rules = parse_policy_toml(path)
        assert rules == []

    def test_unknown_fields_warn(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        path = tmp_path / "warn.toml"
        path.write_text(
            "[[rule]]\n"
            'toolName = "foo"\n'
            'decision = "allow"\n'
            "unknownField = 42\n"
            'anotherBad = "hi"\n',
            encoding="utf-8",
        )
        with caplog.at_level(logging.WARNING):
            rules = parse_policy_toml(path)
        assert len(rules) == 1
        assert "unknownField" in caplog.text
        assert "anotherBad" in caplog.text

    def test_schema_version_warning(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        path = tmp_path / "v2.toml"
        path.write_text(
            'schema_version = "2"\n\n[[rule]]\ntoolName = "foo"\ndecision = "allow"\n',
            encoding="utf-8",
        )
        with caplog.at_level(logging.WARNING):
            parse_policy_toml(path)
        assert "schema_version 2" in caplog.text

    def test_invalid_priority_type(self, tmp_path: Path) -> None:
        path = tmp_path / "bad.toml"
        path.write_text(
            '[[rule]]\ntoolName = "foo"\ndecision = "allow"\npriority = "high"\n',
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="'priority' must be an integer"):
            parse_policy_toml(path)


class TestValidateRules:
    def test_valid_rules_pass(self) -> None:
        rules = [
            ToolRule(tool_name="foo", decision=Decision.ALLOW),
            ToolRule(tool_name="*", decision=Decision.ASK_USER),
        ]
        validate_rules(rules)  # should not raise

    def test_empty_tool_name_fails(self) -> None:
        rules = [ToolRule(tool_name="", decision=Decision.DENY)]
        with pytest.raises(ValueError, match="tool_name is empty"):
            validate_rules(rules)

    def test_whitespace_tool_name_fails(self) -> None:
        rules = [ToolRule(tool_name="   ", decision=Decision.ALLOW)]
        with pytest.raises(ValueError, match="tool_name is empty"):
            validate_rules(rules)
