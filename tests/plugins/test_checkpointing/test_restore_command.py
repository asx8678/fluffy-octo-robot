"""Tests for restore_command.py."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from code_muse.plugins.checkpointing.restore_command import (
    _get_commit_hash_for_snapshot,
    _handle_restore_command,
    _hash_project_root,
)


def test_list_checkpoints_empty(mock_project_root: Path) -> None:
    with (
        patch(
            "code_muse.plugins.checkpointing.conversation_snapshots.list_snapshots",
            return_value=[],
        ),
        patch("code_muse.messaging.emit_info") as mock_emit,
    ):
        result = _handle_restore_command("/restore")
        assert result is True
        assert "No checkpoints available yet" in str(mock_emit.call_args)


def test_list_checkpoints(mock_project_root: Path) -> None:
    with (
        patch(
            "code_muse.plugins.checkpointing.conversation_snapshots.list_snapshots",
            return_value=[
                {
                    "timestamp": "2025-01-01T00:00:00+00:00",
                    "tool_name": "write_file",
                    "tool_call_id": "",
                    "path": str(mock_project_root / "snap.json"),
                }
            ],
        ),
        patch("code_muse.messaging.emit_info") as mock_emit,
    ):
        result = _handle_restore_command("/restore")
        assert result is True
        text = str(mock_emit.call_args_list)
        assert "Available checkpoints" in text or "write_file" in text


def test_restore_invalid_index(mock_project_root: Path) -> None:
    with patch("code_muse.messaging.emit_error") as mock_emit:
        result = _handle_restore_command("/restore 99")
        assert result is True
        assert "out of range" in str(mock_emit.call_args)


def test_restore_bad_scope(mock_project_root: Path) -> None:
    with patch("code_muse.messaging.emit_error") as mock_emit:
        result = _handle_restore_command("/restore 1 bad_scope")
        assert result is True
        assert "scope must be one of" in str(mock_emit.call_args)


def test_get_commit_hash_for_snapshot(mock_project_root: Path) -> None:
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="abc123 checkpoint: write_file 2025-01-01T00:00:00+00:00\n",
            stderr="",
        )
        selected = {
            "timestamp": "2025-01-01T00:00:00+00:00",
            "tool_name": "write_file",
        }
        commit = _get_commit_hash_for_snapshot(selected, mock_project_root)
        assert commit == "abc123"


def test_hash_project_root() -> None:
    h1 = _hash_project_root("/foo/bar")
    h2 = _hash_project_root("/foo/bar")
    h3 = _hash_project_root("/foo/baz")
    assert h1 == h2
    assert h1 != h3
