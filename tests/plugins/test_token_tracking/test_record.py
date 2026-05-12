"""Tests for the token tracking record module."""

from unittest.mock import MagicMock, patch

from code_muse.plugins.token_tracking.record import (
    _count_tokens,
    record_command,
)


class TestCountTokens:
    """Token counting heuristic."""

    def test_empty_string(self) -> None:
        assert _count_tokens("") == 0

    def test_whitespace_only(self) -> None:
        assert _count_tokens("   \n\t  ") == 0

    def test_simple_words(self) -> None:
        assert _count_tokens("hello world") == 2

    def test_multi_line(self) -> None:
        assert _count_tokens("line one\nline two\nline three") == 6


class TestRecordCommand:
    """Recording executions to the tracking database."""

    def test_records_successfully(self) -> None:
        mock_db = MagicMock()
        mock_db.insert.return_value = 42

        with (
            patch(
                "code_muse.plugins.token_tracking.record.get_tracking_db",
                return_value=mock_db,
            ),
            patch(
                "code_muse.plugins.token_tracking.record.get_current_autosave_id",
                return_value="test-session-id",
            ),
        ):
            record_command(
                command="git status",
                raw_stdout="## main\n M file.py\n",
                raw_stderr="",
                compressed_stdout="branch:main\n1 modified\n",
                compressed_stderr="",
                category="git",
                strategy="compress_git_status",
                exit_code=0,
            )

        mock_db.insert.assert_called_once()
        call_kwargs = mock_db.insert.call_args.kwargs
        assert call_kwargs["command"] == "git status"
        assert call_kwargs["category"] == "git"
        assert call_kwargs["strategy"] == "compress_git_status"
        assert call_kwargs["raw_tokens"] == 4
        assert call_kwargs["compressed_tokens"] == 3
        assert call_kwargs["savings_pct"] == 25.0
        assert call_kwargs["exit_code"] == 0
        assert call_kwargs["session_id"] == "test-session-id"

    def test_zero_raw_tokens_savings_zero(self) -> None:
        mock_db = MagicMock()

        with patch(
            "code_muse.plugins.token_tracking.record.get_tracking_db",
            return_value=mock_db,
        ):
            record_command(
                command="echo",
                raw_stdout="",
                raw_stderr="",
                compressed_stdout="",
                compressed_stderr="",
                category="unknown",
                strategy="passthrough",
            )

        assert mock_db.insert.call_args.kwargs["savings_pct"] == 0.0

    def test_never_raises_on_db_failure(self) -> None:
        with patch(
            "code_muse.plugins.token_tracking.record.get_tracking_db",
            side_effect=RuntimeError("db locked"),
        ):
            # Should not raise
            record_command(
                command="git status",
                raw_stdout="foo",
                raw_stderr="bar",
                compressed_stdout="baz",
                compressed_stderr="",
                category="git",
                strategy="compress_git_status",
            )

    def test_duration_ms_passed_through(self) -> None:
        mock_db = MagicMock()

        with patch(
            "code_muse.plugins.token_tracking.record.get_tracking_db",
            return_value=mock_db,
        ):
            record_command(
                command="sleep 1",
                raw_stdout="",
                raw_stderr="",
                compressed_stdout="",
                compressed_stderr="",
                category="unknown",
                strategy="passthrough",
                duration_ms=1234.5,
            )

        assert mock_db.insert.call_args.kwargs["duration_ms"] == 1234.5
