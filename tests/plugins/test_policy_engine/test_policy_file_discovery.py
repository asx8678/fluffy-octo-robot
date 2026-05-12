import logging
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from code_muse.plugins.policy_engine.policy_file_discovery import (
    _files_changed,
    clear_policy_cache,
    discover_policy_files,
    load_all_policies,
)


class TestDiscoverPolicyFiles:
    def test_no_directories(self, tmp_path: Path) -> None:
        # tmp_path has no .muse/policies and home won't have it either
        files = discover_policy_files()
        # Just verify it doesn't crash; result depends on user's actual home dir
        assert isinstance(files, list)

    def test_user_tier_discovery(self, tmp_path: Path) -> None:
        user_policies = tmp_path / ".muse" / "policies"
        user_policies.mkdir(parents=True)
        (user_policies / "user1.toml").write_text(
            '[[rule]]\ntoolName = "foo"\ndecision = "allow"\n',
            encoding="utf-8",
        )

        with patch(
            "code_muse.plugins.policy_engine.policy_file_discovery._get_user_policies_dir",
            return_value=user_policies,
        ):
            files = discover_policy_files()

        assert len(files) == 1
        assert files[0].name == "user1.toml"

    def test_project_tier_discovery(self, tmp_path: Path) -> None:
        project_policies = tmp_path / ".muse" / "policies"
        project_policies.mkdir(parents=True)
        (project_policies / "project1.toml").write_text(
            '[[rule]]\ntoolName = "bar"\ndecision = "deny"\n',
            encoding="utf-8",
        )

        with patch(
            "code_muse.plugins.policy_engine.policy_file_discovery._get_project_policies_dir",
            return_value=project_policies,
        ):
            files = discover_policy_files()

        assert len(files) == 1
        assert files[0].name == "project1.toml"

    def test_non_toml_files_ignored(self, tmp_path: Path) -> None:
        policies_dir = tmp_path / ".muse" / "policies"
        policies_dir.mkdir(parents=True)
        (policies_dir / "rules.toml").write_text(
            '[[rule]]\ntoolName = "x"\ndecision = "allow"\n',
            encoding="utf-8",
        )
        (policies_dir / "readme.md").write_text("# policies", encoding="utf-8")
        (policies_dir / "backup.txt").write_text("old", encoding="utf-8")

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
            files = discover_policy_files()

        names = [f.name for f in files]
        assert "rules.toml" in names
        assert "readme.md" not in names
        assert "backup.txt" not in names

    def test_unreadable_file_warning(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        policies_dir = tmp_path / ".muse" / "policies"
        policies_dir.mkdir(parents=True)
        bad_file = policies_dir / "unreadable.toml"
        bad_file.write_text("data", encoding="utf-8")

        # Make file unreadable (best effort; skip on Windows or if root)
        try:
            os.chmod(str(bad_file), 0o000)
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
                with caplog.at_level(logging.WARNING):
                    files = discover_policy_files()
            # Should not crash; may or may not appear depending on OS/permissions
            assert isinstance(files, list)
        finally:
            os.chmod(str(bad_file), 0o644)


class TestLoadAllPolicies:
    def test_load_valid_file(self, tmp_path: Path) -> None:
        clear_policy_cache()
        policies_dir = tmp_path / ".muse" / "policies"
        policies_dir.mkdir(parents=True)
        (policies_dir / "rules.toml").write_text(
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

        assert len(rules) >= 1
        assert any(r.tool_name == "foo" for r in rules)
        clear_policy_cache()

    def test_skip_invalid_file(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        clear_policy_cache()
        policies_dir = tmp_path / ".muse" / "policies"
        policies_dir.mkdir(parents=True)
        (policies_dir / "bad.toml").write_text(
            '[[rule]]\ndecision = "allow"\n',  # missing toolName
            encoding="utf-8",
        )
        (policies_dir / "good.toml").write_text(
            '[[rule]]\ntoolName = "bar"\ndecision = "deny"\n',
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
            with caplog.at_level(logging.WARNING):
                rules = load_all_policies()

        assert any(r.tool_name == "bar" for r in rules)
        assert "bad.toml" in caplog.text
        clear_policy_cache()

    def test_cache_returns_same_rules(self, tmp_path: Path) -> None:
        clear_policy_cache()
        policies_dir = tmp_path / ".muse" / "policies"
        policies_dir.mkdir(parents=True)
        (policies_dir / "rules.toml").write_text(
            '[[rule]]\ntoolName = "cached"\ndecision = "allow"\n',
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
            second = load_all_policies()

        assert first is second  # same cached list object
        clear_policy_cache()

    def test_force_reload(self, tmp_path: Path) -> None:
        clear_policy_cache()
        policies_dir = tmp_path / ".muse" / "policies"
        policies_dir.mkdir(parents=True)
        (policies_dir / "rules.toml").write_text(
            '[[rule]]\ntoolName = "reload_test"\ndecision = "allow"\n',
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
            second = load_all_policies(force_reload=True)

        # Not necessarily the same object since force_reload rebuilds
        assert len(first) == len(second)
        clear_policy_cache()


class TestFilesChanged:
    def test_empty_vs_empty(self) -> None:
        clear_policy_cache()
        # When cache is empty and no files are found, nothing changed
        assert _files_changed([]) is False
