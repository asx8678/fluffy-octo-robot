"""End-to-end integration tests for the filter engine.

Tests the full pipeline: command → classified → filtered → returned.
"""

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from code_muse.plugins.filter_engine.classifier import CommandClassifier
from code_muse.plugins.filter_engine.dispatcher import FilterDispatcher
from code_muse.plugins.filter_engine.registry import get_registry
from code_muse.plugins.filter_engine.verbosity import VerbosityLevel
from code_muse.tools.command_runner import ShellCommandOutput


class TestEndToEnd:
    """Full pipeline integration."""

    @pytest.fixture
    def dispatcher(self) -> FilterDispatcher:
        return FilterDispatcher()

    @pytest.fixture
    def mock_shell_output(self) -> ShellCommandOutput:
        return ShellCommandOutput(
            success=True,
            command="git status",
            stdout=(
                "## main...origin/main [ahead 2, behind 0]\n"
                " M src/core.py\n"
                " A tests/test_core.py\n"
                "?? docs/new.md\n"
            ),
            stderr="",
            exit_code=0,
            execution_time=0.1,
        )

    @pytest.mark.asyncio
    async def test_git_status_pipeline(
        self,
        dispatcher: FilterDispatcher,
        mock_shell_output: ShellCommandOutput,
    ) -> None:
        """Full pipeline for git status → classification → filtering → result."""
        with (
            patch(
                "code_muse.plugins.filter_engine.dispatcher._execute_shell_command",
                new_callable=AsyncMock,
                return_value=mock_shell_output,
            ),
            patch(
                "code_muse.plugins.filter_engine.dispatcher.get_verbosity",
                return_value=VerbosityLevel.COMPACT,
            ),
        ):
            result = await dispatcher.handle(None, "git status", "/tmp/repo", 60)

        assert result is not None
        assert result.get("pre_executed") is True
        output = result["output"]
        assert isinstance(output, ShellCommandOutput)
        assert output.success is True
        assert "branch:main" in (output.stdout or "")
        assert "↑2" in (output.stdout or "")

    @pytest.mark.asyncio
    async def test_pytest_pipeline(self, dispatcher: FilterDispatcher) -> None:
        """Full pipeline for pytest → classification → filtering → result."""
        shell_out = ShellCommandOutput(
            success=False,
            command="pytest",
            stdout=(
                "tests/test_x.py::test_foo PASSED\n"
                "tests/test_x.py::test_bar FAILED\n"
                "= 1 passed, 1 failed in 0.5s =\n"
            ),
            stderr="",
            exit_code=1,
            execution_time=2.0,
        )
        with (
            patch(
                "code_muse.plugins.filter_engine.dispatcher._execute_shell_command",
                new_callable=AsyncMock,
                return_value=shell_out,
            ),
            patch(
                "code_muse.plugins.filter_engine.dispatcher.get_verbosity",
                return_value=VerbosityLevel.COMPACT,
            ),
        ):
            result = await dispatcher.handle(None, "pytest", None, 60)

        assert result is not None
        output = result["output"]
        assert "FAILED" in (output.stdout or "")
        assert output.exit_code == 1

    @pytest.mark.asyncio
    async def test_ruff_pipeline(self, dispatcher: FilterDispatcher) -> None:
        """Full pipeline for ruff → classification → filtering → result."""
        shell_out = ShellCommandOutput(
            success=True,
            command="ruff check .",
            stdout=(
                "src/a.py:1:1: E501 Line too long\nsrc/b.py:2:1: F401 Unused import\n"
            ),
            stderr="",
            exit_code=0,
            execution_time=0.5,
        )
        with (
            patch(
                "code_muse.plugins.filter_engine.dispatcher._execute_shell_command",
                new_callable=AsyncMock,
                return_value=shell_out,
            ),
            patch(
                "code_muse.plugins.filter_engine.dispatcher.get_verbosity",
                return_value=VerbosityLevel.COMPACT,
            ),
        ):
            result = await dispatcher.handle(None, "ruff check .", None, 60)

        assert result is not None
        output = result["output"]
        assert "E501" in (output.stdout or "")
        assert "F401" in (output.stdout or "")

    @pytest.mark.asyncio
    async def test_cat_pipeline(self, dispatcher: FilterDispatcher) -> None:
        """Full pipeline for cat → classification → filtering → result."""
        code = "import os\n# comment\ndef foo():\n    return 1\n"
        shell_out = ShellCommandOutput(
            success=True,
            command="cat file.py",
            stdout=code,
            stderr="",
            exit_code=0,
            execution_time=0.1,
        )
        with (
            patch(
                "code_muse.plugins.filter_engine.dispatcher._execute_shell_command",
                new_callable=AsyncMock,
                return_value=shell_out,
            ),
            patch(
                "code_muse.plugins.filter_engine.dispatcher.get_verbosity",
                return_value=VerbosityLevel.COMPACT,
            ),
        ):
            result = await dispatcher.handle(None, "cat file.py", None, 60)

        assert result is not None
        output = result["output"]
        assert "import os" in (output.stdout or "")
        assert "# comment" not in (output.stdout or "")

    @pytest.mark.asyncio
    async def test_unknown_passthrough(self, dispatcher: FilterDispatcher) -> None:
        """Unknown commands should passthrough (return None)."""
        with patch(
            "code_muse.plugins.filter_engine.dispatcher._execute_shell_command",
            new_callable=AsyncMock,
        ) as mock_exec:
            result = await dispatcher.handle(None, "docker ps", None, 60)
            assert result is None
            mock_exec.assert_not_called()


class TestRegistryIntegration:
    """Registry integration with real strategies."""

    def test_all_categories_registered(self) -> None:
        registry = get_registry()
        categories = registry.list_categories()
        for cat in ("git", "test", "lint", "code", "read", "unknown"):
            assert cat in categories

    def test_strategy_callable(self) -> None:
        registry = get_registry()
        for cat in ("git", "test", "lint", "code", "read"):
            strategy = registry.get_strategy(cat)
            assert strategy is not None
            assert callable(strategy)


class TestClassifierIntegration:
    """Classifier integration with real commands."""

    @pytest.mark.parametrize(
        "command,category",
        [
            ("git status", "git"),
            ("pytest", "test"),
            ("ruff check .", "lint"),
            ("cat file.py", "read"),
            ("ls -la", "code"),
            ("docker ps", "unknown"),
        ],
    )
    def test_classification(self, command: str, category: str) -> None:
        assert CommandClassifier.classify(command) == category


class TestInitCommand:
    """``/init`` custom command integration."""

    def test_init_command_creates_muse_md(self, tmp_path: Path) -> None:
        from code_muse.plugins.filter_engine.register_callbacks import (
            _on_custom_command,
        )

        # Create a fake pyproject.toml in temp dir
        (tmp_path / "pyproject.toml").write_text("[project]\n")

        # Patch cwd and messaging
        with (
            patch(
                "code_muse.plugins.filter_engine.register_callbacks.Path.cwd",
                return_value=tmp_path,
            ),
            patch(
                "code_muse.plugins.filter_engine.register_callbacks.emit_success"
            ) as mock_emit,
        ):
            result = _on_custom_command("/init", "init")
            assert result is True
            mock_emit.assert_called_once()
            assert "Muse initialized" in mock_emit.call_args[0][0]

        md_path = tmp_path / "MUSE.md"
        assert md_path.exists()
        content = md_path.read_text()
        assert "Muse Token Saving" in content
        assert "Enabled Strategies" in content

    def test_init_command_skips_existing(self, tmp_path: Path) -> None:
        from code_muse.plugins.filter_engine.register_callbacks import (
            _on_custom_command,
        )

        # Pre-create MUSE.md
        (tmp_path / "MUSE.md").write_text("existing")

        with (
            patch(
                "code_muse.plugins.filter_engine.register_callbacks.Path.cwd",
                return_value=tmp_path,
            ),
            patch(
                "code_muse.plugins.filter_engine.register_callbacks.emit_info"
            ) as mock_emit,
        ):
            result = _on_custom_command("/init", "init")
            assert result is True
            mock_emit.assert_called_once()
            assert "already exists" in mock_emit.call_args[0][0]

    def test_init_command_wrong_name_returns_none(self) -> None:
        from code_muse.plugins.filter_engine.register_callbacks import (
            _on_custom_command,
        )

        result = _on_custom_command("/something", "something")
        assert result is None
