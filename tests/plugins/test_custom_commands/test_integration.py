from pathlib import Path
from unittest.mock import patch

from code_muse.plugins.custom_commands.command_discovery import discover_commands
from code_muse.plugins.custom_commands.register_callbacks import (
    CustomCommandResult,
    _load_commands,
    _on_custom_command,
    _reload_commands,
)


class TestIntegration:
    def test_full_flow_flat_command(self, tmp_path: Path) -> None:
        user_dir = tmp_path / "user"
        user_dir.mkdir(parents=True)
        (user_dir / "review.toml").write_text(
            'prompt = "Review this file: {{args}}"\ndescription = "Code review"'
        )

        commands = discover_commands(
            user_dir=user_dir, project_dir=tmp_path / "project"
        )
        assert "/review" in commands
        assert commands["/review"].description == "Code review"

        with patch(
            "code_muse.plugins.custom_commands.register_callbacks.discover_commands",
            return_value=commands,
        ):
            _reload_commands()
            result = _on_custom_command("/review src/main.py", "review")
        assert isinstance(result, CustomCommandResult)
        assert result.content == "Review this file: src/main.py"

    def test_full_flow_namespaced_command(self, tmp_path: Path) -> None:
        user_dir = tmp_path / "user"
        (user_dir / "git").mkdir(parents=True)
        (user_dir / "git" / "fix.toml").write_text(
            'prompt = "Fix the bug described: {{args}}"\ndescription = "Git fix helper"'
        )

        commands = discover_commands(
            user_dir=user_dir, project_dir=tmp_path / "project"
        )
        assert "/git:fix" in commands

        with patch(
            "code_muse.plugins.custom_commands.register_callbacks.discover_commands",
            return_value=commands,
        ):
            _reload_commands()
            result = _on_custom_command("/git:fix Button misaligned", "git:fix")
        assert isinstance(result, CustomCommandResult)
        assert result.content == "Fix the bug described: Button misaligned"

    def test_full_flow_with_shell_flags(self, tmp_path: Path) -> None:
        user_dir = tmp_path / "user"
        user_dir.mkdir(parents=True)
        (user_dir / "test.toml").write_text(
            'prompt = """Run tests:\n```bash\nnpm install\ncargo test\n```\n"""'
        )

        commands = discover_commands(
            user_dir=user_dir, project_dir=tmp_path / "project"
        )

        with patch(
            "code_muse.plugins.custom_commands.register_callbacks.discover_commands",
            return_value=commands,
        ):
            _reload_commands()
            result = _on_custom_command("/test", "test")
        assert isinstance(result, CustomCommandResult)
        assert "npm install --silent" in result.content
        assert "cargo test --quiet" in result.content

    def test_full_flow_empty_args(self, tmp_path: Path) -> None:
        user_dir = tmp_path / "user"
        user_dir.mkdir(parents=True)
        (user_dir / "lint.toml").write_text('prompt = "Lint the project {{args}}"')

        commands = discover_commands(
            user_dir=user_dir, project_dir=tmp_path / "project"
        )
        assert "/lint" in commands

        with patch(
            "code_muse.plugins.custom_commands.register_callbacks.discover_commands",
            return_value=commands,
        ):
            _reload_commands()
            result = _on_custom_command("/lint", "lint")
        assert isinstance(result, CustomCommandResult)
        assert result.content == "Lint the project "

    def test_project_override_user(self, tmp_path: Path) -> None:
        user_dir = tmp_path / "user"
        project_dir = tmp_path / "project"
        user_dir.mkdir(parents=True)
        project_dir.mkdir(parents=True)
        (user_dir / "deploy.toml").write_text('prompt = "User deploy"')
        (project_dir / "deploy.toml").write_text('prompt = "Project deploy"')

        commands = discover_commands(user_dir=user_dir, project_dir=project_dir)

        with patch(
            "code_muse.plugins.custom_commands.register_callbacks.discover_commands",
            return_value=commands,
        ):
            _reload_commands()
            result = _on_custom_command("/deploy", "deploy")
        assert isinstance(result, CustomCommandResult)
        assert result.content == "Project deploy"

    def test_command_not_found_returns_none(self) -> None:
        assert _on_custom_command("/nonexistent", "nonexistent") is None

    def test_commands_list(self, tmp_path: Path) -> None:
        user_dir = tmp_path / "user"
        user_dir.mkdir(parents=True)
        (user_dir / "a.toml").write_text('prompt = "A"')
        (user_dir / "b.toml").write_text('prompt = "B"\ndescription = "Desc B"')

        with patch(
            "code_muse.plugins.custom_commands.register_callbacks._command_cache",
            discover_commands(user_dir=user_dir, project_dir=tmp_path / "project"),
        ):
            _load_commands()
            result = _on_custom_command("/commands list", "commands")
            assert result is True

    def test_commands_reload(self, tmp_path: Path) -> None:
        user_dir = tmp_path / "user"
        user_dir.mkdir(parents=True)
        (user_dir / "cmd.toml").write_text('prompt = "Cmd"')

        with patch(
            "code_muse.plugins.custom_commands.register_callbacks.discover_commands",
            return_value=discover_commands(
                user_dir=user_dir, project_dir=tmp_path / "project"
            ),
        ):
            result = _on_custom_command("/commands reload", "commands")
            assert result is True
