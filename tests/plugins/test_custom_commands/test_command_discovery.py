from pathlib import Path

import pytest

from code_muse.plugins.custom_commands.command_discovery import (
    _resolve_namespace,
    discover_commands,
)


class TestResolveNamespace:
    def test_flat_file(self) -> None:
        base = Path("/root/commands")
        assert _resolve_namespace(base / "fix.toml", base) == "/fix"

    def test_subdir_file(self) -> None:
        base = Path("/root/commands")
        assert _resolve_namespace(base / "git" / "fix.toml", base) == "/git:fix"

    def test_nested_subdir(self) -> None:
        base = Path("/root/commands")
        assert _resolve_namespace(base / "a" / "b" / "c.toml", base) == "/a:b:c"


class TestDiscoverCommands:
    def test_flat_namespacing(self, tmp_path: Path) -> None:
        user_dir = tmp_path / "user"
        user_dir.mkdir()
        (user_dir / "fix.toml").write_text('prompt = "Fix it"')

        result = discover_commands(user_dir=user_dir, project_dir=tmp_path / "project")
        assert "/fix" in result
        assert result["/fix"].prompt == "Fix it"

    def test_subdir_namespacing(self, tmp_path: Path) -> None:
        user_dir = tmp_path / "user"
        (user_dir / "git").mkdir(parents=True)
        (user_dir / "git" / "status.toml").write_text('prompt = "Show status"')

        result = discover_commands(user_dir=user_dir, project_dir=tmp_path / "project")
        assert "/git:status" in result
        assert result["/git:status"].prompt == "Show status"

    def test_project_overrides_user(self, tmp_path: Path) -> None:
        user_dir = tmp_path / "user"
        project_dir = tmp_path / "project"
        user_dir.mkdir(parents=True)
        project_dir.mkdir(parents=True)
        (user_dir / "fix.toml").write_text('prompt = "User fix"')
        (project_dir / "fix.toml").write_text('prompt = "Project fix"')

        result = discover_commands(user_dir=user_dir, project_dir=project_dir)
        assert result["/fix"].prompt == "Project fix"

    def test_invalid_filenames_warn_and_skip(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        user_dir = tmp_path / "user"
        user_dir.mkdir()
        (user_dir / "bad name!.toml").write_text('prompt = "Bad"')

        with caplog.at_level("WARNING"):
            result = discover_commands(
                user_dir=user_dir, project_dir=tmp_path / "project"
            )
        assert "/bad name!" not in result
        assert "Skipping invalid command filename" in caplog.text

    def test_empty_directories_handled(self, tmp_path: Path) -> None:
        user_dir = tmp_path / "user"
        user_dir.mkdir()
        result = discover_commands(user_dir=user_dir, project_dir=tmp_path / "project")
        assert result == {}

    def test_hidden_files_skipped(self, tmp_path: Path) -> None:
        user_dir = tmp_path / "user"
        user_dir.mkdir(parents=True)
        (user_dir / ".hidden.toml").write_text('prompt = "Hidden"')
        (user_dir / "visible.toml").write_text('prompt = "Visible"')

        result = discover_commands(user_dir=user_dir, project_dir=tmp_path / "project")
        assert "/.hidden" not in result
        assert "/visible" in result

    def test_invalid_toml_warns_and_skips(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        user_dir = tmp_path / "user"
        user_dir.mkdir(parents=True)
        (user_dir / "bad.toml").write_text("not valid toml !!!")

        with caplog.at_level("WARNING"):
            result = discover_commands(
                user_dir=user_dir, project_dir=tmp_path / "project"
            )
        assert "/bad" not in result
        assert "Failed to load command" in caplog.text
