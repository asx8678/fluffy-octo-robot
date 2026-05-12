"""Tests for the filter dispatcher."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from code_muse.plugins.filter_engine.dispatcher import FilterDispatcher
from code_muse.plugins.filter_engine.verbosity import VerbosityLevel
from code_muse.tools.command_runner import ShellCommandOutput


class TestDispatcherPipeline:
    """Dispatcher filtering pipeline."""

    @pytest.fixture
    def dispatcher(self) -> FilterDispatcher:
        return FilterDispatcher()

    def test_normalize_plain_git_status(self, dispatcher: FilterDispatcher) -> None:
        assert dispatcher._normalize_command("git status") == (
            "git status --porcelain -b"
        )
        assert dispatcher._normalize_command("git -C /repo status") == (
            "git -C /repo status --porcelain -b"
        )

    def test_normalize_noop_for_porcelain(self, dispatcher: FilterDispatcher) -> None:
        assert dispatcher._normalize_command("git status --porcelain") == (
            "git status --porcelain"
        )
        assert dispatcher._normalize_command("git status --short") == (
            "git status --short"
        )
        assert dispatcher._normalize_command("git status -s") == "git status -s"

    def test_normalize_noop_for_non_git(self, dispatcher: FilterDispatcher) -> None:
        assert dispatcher._normalize_command("echo hello") == "echo hello"
        assert dispatcher._normalize_command("git log") == "git log"

    @pytest.mark.asyncio
    async def test_passthrough_unknown(self, dispatcher: FilterDispatcher) -> None:
        result = await dispatcher.handle(None, "echo hello", None, 60)
        assert result is None

    @pytest.mark.asyncio
    async def test_passthrough_raw_verbosity(
        self, dispatcher: FilterDispatcher
    ) -> None:
        with patch(
            "code_muse.plugins.filter_engine.dispatcher.get_verbosity",
            return_value=VerbosityLevel.RAW,
        ):
            result = await dispatcher.handle(None, "git status", None, 60)
            assert result is None

    @pytest.mark.asyncio
    async def test_git_status_filtering(self, dispatcher: FilterDispatcher) -> None:
        mock_output = ShellCommandOutput(
            success=True,
            command="git status",
            stdout="## main\n M file.py\n",
            stderr="",
            exit_code=0,
            execution_time=0.1,
        )
        with patch(
            "code_muse.plugins.filter_engine.dispatcher._execute_shell_command",
            new_callable=AsyncMock,
            return_value=mock_output,
        ) as mock_exec:
            result = await dispatcher.handle(None, "git status", None, 60)
            assert result is not None
            assert result.get("pre_executed") is True
            assert isinstance(result.get("output"), ShellCommandOutput)
            out = result["output"]
            assert "branch:main" in (out.stdout or "")
            # Verify the command was rewritten to force porcelain
            mock_exec.assert_awaited_once()
            call_kwargs = mock_exec.call_args.kwargs
            assert call_kwargs["command"] == "git status --porcelain -b"

    @pytest.mark.asyncio
    async def test_strategy_exception_fallback(
        self, dispatcher: FilterDispatcher
    ) -> None:
        with patch(
            "code_muse.plugins.filter_engine.dispatcher._execute_shell_command",
            new_callable=AsyncMock,
            side_effect=RuntimeError("boom"),
        ):
            result = await dispatcher.handle(None, "git status", None, 60)
            # Tee recovery now returns a hint instead of None
            assert result is not None
            assert result.get("pre_executed") is True
            out = result["output"]
            assert isinstance(out, ShellCommandOutput)
            assert out.success is False
            assert "Filter error" in out.stdout
            assert "muse_tee" in out.stdout

    @pytest.mark.asyncio
    async def test_strategy_returns_none(self, dispatcher: FilterDispatcher) -> None:
        mock_output = ShellCommandOutput(
            success=True,
            command="git status",
            stdout="",
            stderr="",
            exit_code=0,
            execution_time=0.1,
        )
        with (
            patch(
                "code_muse.plugins.filter_engine.dispatcher._execute_shell_command",
                new_callable=AsyncMock,
                return_value=mock_output,
            ),
            patch.object(
                dispatcher.classifier,
                "classify",
                return_value="git",
            ),
            patch(
                "code_muse.plugins.filter_engine.dispatcher.get_registry",
            ) as mock_get_registry,
        ):
            mock_registry = MagicMock()
            mock_registry.get_strategy.return_value = lambda *args, **kwargs: None
            mock_get_registry.return_value = mock_registry
            result = await dispatcher.handle(None, "git status", None, 60)
            assert result is None

    @pytest.mark.asyncio
    async def test_tee_recovery_on_exception(
        self, dispatcher: FilterDispatcher
    ) -> None:
        """When strategy raises, tee file is created and hint is returned."""
        import tempfile

        mock_output = ShellCommandOutput(
            success=True,
            command="git status",
            stdout="raw stdout content",
            stderr="raw stderr content",
            exit_code=0,
            execution_time=0.1,
        )

        def _boom(*args, **kwargs) -> None:
            raise RuntimeError("strategy explosion")

        with (
            patch(
                "code_muse.plugins.filter_engine.dispatcher._execute_shell_command",
                new_callable=AsyncMock,
                return_value=mock_output,
            ),
            patch.object(
                dispatcher.classifier,
                "classify",
                return_value="git",
            ),
            patch(
                "code_muse.plugins.filter_engine.dispatcher.get_registry",
            ) as mock_get_registry,
        ):
            mock_registry = MagicMock()
            mock_registry.get_strategy.return_value = _boom
            mock_get_registry.return_value = mock_registry

            result = await dispatcher.handle(None, "git status", None, 60)

        assert result is not None
        assert result.get("pre_executed") is True
        out = result["output"]
        assert isinstance(out, ShellCommandOutput)
        assert out.success is False
        assert "Filter error" in out.stdout
        assert "muse_tee" in out.stdout

        # Verify tee file exists
        tee_dir = Path(tempfile.gettempdir()) / "muse_tee"
        if tee_dir.exists():
            tee_files = list(tee_dir.glob("tee_*.txt"))
            assert len(tee_files) > 0
            latest = max(tee_files, key=lambda p: p.stat().st_mtime)
            content = latest.read_text()
            assert "raw stdout content" in content
            assert "raw stderr content" in content
            assert "git status" in content
            # Cleanup
            latest.unlink()
