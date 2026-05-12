"""Tests for filter-engine → token-tracking integration."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from code_muse.plugins.filter_engine.dispatcher import FilterDispatcher
from code_muse.plugins.filter_engine.verbosity import VerbosityLevel
from code_muse.tools.command_runner import ShellCommandOutput


def _fake_strategy(
    command: str,
    stdout: str,
    stderr: str,
    exit_code: int,
    verbosity: VerbosityLevel,
) -> ShellCommandOutput:
    """A fake strategy that returns compressed output."""
    return ShellCommandOutput(
        success=True,
        command=command,
        stdout=stdout.replace("## main", "branch:main"),
        stderr=stderr,
        exit_code=exit_code,
        execution_time=0.1,
    )


class TestDispatcherTrackingIntegration:
    """Dispatcher calls record_command after successful filtering."""

    @pytest.fixture
    def dispatcher(self) -> FilterDispatcher:
        return FilterDispatcher()

    @pytest.mark.asyncio
    async def test_tracking_called_on_filtered_output(
        self, dispatcher: FilterDispatcher
    ) -> None:
        mock_output = ShellCommandOutput(
            success=True,
            command="git status",
            stdout="## main\n M file.py\n",
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
            patch(
                "code_muse.plugins.filter_engine.dispatcher.get_registry",
            ) as mock_get_registry,
        ):
            mock_registry = MagicMock()
            mock_registry.get_strategy.return_value = _fake_strategy
            mock_get_registry.return_value = mock_registry
            with patch(
                "code_muse.plugins.token_tracking.record.record_command",
            ) as mock_record:
                result = await dispatcher.handle(None, "git status", None, 60)

        assert result is not None
        mock_record.assert_called_once()
        call_kwargs = mock_record.call_args.kwargs
        assert call_kwargs["command"] == "git status"
        assert call_kwargs["raw_stdout"] == "## main\n M file.py\n"
        assert call_kwargs["raw_stderr"] == ""
        assert call_kwargs["category"] == "git"
        assert "exit_code" in call_kwargs

    @pytest.mark.asyncio
    async def test_tracking_not_called_when_passthrough(
        self, dispatcher: FilterDispatcher
    ) -> None:
        with patch(
            "code_muse.plugins.token_tracking.record.record_command",
        ) as mock_record:
            result = await dispatcher.handle(None, "echo hello", None, 60)

        assert result is None
        mock_record.assert_not_called()

    @pytest.mark.asyncio
    async def test_tracking_not_called_on_raw_verbosity(
        self, dispatcher: FilterDispatcher
    ) -> None:
        with (
            patch(
                "code_muse.plugins.filter_engine.dispatcher.get_verbosity",
                return_value=VerbosityLevel.RAW,
            ),
            patch(
                "code_muse.plugins.token_tracking.record.record_command",
            ) as mock_record,
        ):
            result = await dispatcher.handle(None, "git status", None, 60)

        assert result is None
        mock_record.assert_not_called()

    @pytest.mark.asyncio
    async def test_tracking_survives_exception(
        self, dispatcher: FilterDispatcher
    ) -> None:
        mock_output = ShellCommandOutput(
            success=True,
            command="git status",
            stdout="## main\n M file.py\n",
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
            patch(
                "code_muse.plugins.filter_engine.dispatcher.get_registry",
            ) as mock_get_registry,
        ):
            mock_registry = MagicMock()
            mock_registry.get_strategy.return_value = _fake_strategy
            mock_get_registry.return_value = mock_registry
            with patch(
                "code_muse.plugins.token_tracking.record.record_command",
                side_effect=RuntimeError("db failed"),
            ) as mock_record:
                result = await dispatcher.handle(None, "git status", None, 60)

        # Dispatcher should still return the filtered result even if tracking fails
        assert result is not None
        mock_record.assert_called_once()

    @pytest.mark.asyncio
    async def test_tracking_not_called_when_strategy_returns_none(
        self, dispatcher: FilterDispatcher
    ) -> None:
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
            with patch(
                "code_muse.plugins.token_tracking.record.record_command",
            ) as mock_record:
                result = await dispatcher.handle(None, "git status", None, 60)

        assert result is None
        mock_record.assert_not_called()
