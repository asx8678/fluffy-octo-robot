from pathlib import Path
from unittest.mock import patch

from code_muse.plugins.policy_engine import (
    Decision,
    clear_policy_cache,
    evaluate_policy,
    load_all_policies,
)


class TestEndToEnd:
    def test_toml_file_to_decision(self, tmp_path: Path) -> None:
        clear_policy_cache()
        policies_dir = tmp_path / ".muse" / "policies"
        policies_dir.mkdir(parents=True)
        (policies_dir / "rules.toml").write_text(
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

        # Use distinct directories so files aren't double-counted
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        with (
            patch(
                "code_muse.plugins.policy_engine.policy_file_discovery._get_project_policies_dir",
                return_value=policies_dir,
            ),
            patch(
                "code_muse.plugins.policy_engine.policy_file_discovery._get_user_policies_dir",
                return_value=empty_dir,
            ),
        ):
            rules = load_all_policies()

        assert len(rules) == 3

        # git push should be denied
        decision, matched = evaluate_policy(
            "agent_run_shell_command", "git push origin main", rules
        )
        assert decision == Decision.DENY
        assert matched is not None
        assert matched.description == "Block force push to main"

        # npm test should be allowed
        decision, matched = evaluate_policy(
            "agent_run_shell_command", "npm test --watch", rules
        )
        assert decision == Decision.ALLOW
        assert matched is not None
        assert matched.description == "Auto-approve test runs"

        # unknown tool should ask_user via wildcard
        decision, matched = evaluate_policy("write_file", None, rules)
        assert decision == Decision.ASK_USER
        assert matched is not None
        assert matched.tool_name == "*"

        clear_policy_cache()

    def test_user_and_project_tiers_combined(self, tmp_path: Path) -> None:
        clear_policy_cache()
        user_dir = tmp_path / "user" / ".muse" / "policies"
        user_dir.mkdir(parents=True)
        (user_dir / "user.toml").write_text(
            "[[rule]]\n"
            'toolName = "write_file"\n'
            'decision = "deny"\n'
            "priority = 200\n"
            'description = "User override"\n',
            encoding="utf-8",
        )

        project_dir = tmp_path / "project" / ".muse" / "policies"
        project_dir.mkdir(parents=True)
        (project_dir / "project.toml").write_text(
            "[[rule]]\n"
            'toolName = "write_file"\n'
            'decision = "allow"\n'
            "priority = 100\n"
            'description = "Project default"\n',
            encoding="utf-8",
        )

        with (
            patch(
                "code_muse.plugins.policy_engine.policy_file_discovery._get_user_policies_dir",
                return_value=user_dir,
            ),
            patch(
                "code_muse.plugins.policy_engine.policy_file_discovery._get_project_policies_dir",
                return_value=project_dir,
            ),
        ):
            rules = load_all_policies()

        # User rule has higher priority (200 > 100)
        decision, matched = evaluate_policy("write_file", None, rules)
        assert decision == Decision.DENY
        assert matched is not None
        assert matched.priority == 200

        clear_policy_cache()

    def test_invalid_file_skipped_valid_loaded(self, tmp_path: Path) -> None:
        clear_policy_cache()
        policies_dir = tmp_path / ".muse" / "policies"
        policies_dir.mkdir(parents=True)
        (policies_dir / "bad.toml").write_text(
            '[[rule]]\ndecision = "allow"\n',  # missing toolName
            encoding="utf-8",
        )
        (policies_dir / "good.toml").write_text(
            '[[rule]]\ntoolName = "foo"\ndecision = "allow"\n',
            encoding="utf-8",
        )

        with (
            patch(
                "code_muse.plugins.policy_engine.policy_file_discovery._get_project_policies_dir",
                return_value=policies_dir,
            ),
            patch(
                "code_muse.plugins.policy_engine.policy_file_discovery._get_user_policies_dir",
                return_value=policies_dir,
            ),
        ):
            rules = load_all_policies()

        assert any(r.tool_name == "foo" for r in rules)
        clear_policy_cache()

    def test_reload_clears_and_reloads(self, tmp_path: Path) -> None:
        clear_policy_cache()
        policies_dir = tmp_path / ".muse" / "policies"
        policies_dir.mkdir(parents=True)
        (policies_dir / "rules.toml").write_text(
            '[[rule]]\ntoolName = "reload"\ndecision = "allow"\n',
            encoding="utf-8",
        )

        with (
            patch(
                "code_muse.plugins.policy_engine.policy_file_discovery._get_project_policies_dir",
                return_value=policies_dir,
            ),
            patch(
                "code_muse.plugins.policy_engine.policy_file_discovery._get_user_policies_dir",
                return_value=policies_dir,
            ),
        ):
            first = load_all_policies()
            assert any(r.tool_name == "reload" for r in first)

            # Overwrite file
            (policies_dir / "rules.toml").write_text(
                '[[rule]]\ntoolName = "reload"\ndecision = "deny"\n',
                encoding="utf-8",
            )

            second = load_all_policies(force_reload=True)
            matched = next(r for r in second if r.tool_name == "reload")
            assert matched.decision == Decision.DENY

        clear_policy_cache()
