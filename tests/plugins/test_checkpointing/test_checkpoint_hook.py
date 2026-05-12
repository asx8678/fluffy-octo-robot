"""Tests for checkpoint_hook.py."""

import asyncio
from unittest.mock import patch

from code_muse.plugins.checkpointing.checkpoint_hook import (
    _extract_affected_files,
    on_pre_tool_call_checkpoint,
)


def test_hook_ignores_non_file_tools() -> None:
    result = asyncio.run(
        on_pre_tool_call_checkpoint("read_file", {"file_path": "foo.py"})
    )
    assert result is None


def test_hook_fires_for_write_file() -> None:
    with (
        patch("asyncio.create_task") as mock_create_task,
        patch(
            "code_muse.plugins.checkpointing.checkpoint_hook._create_checkpoint_async"
        ) as mock_checkpoint,
    ):
        mock_checkpoint.return_value = None
        result = asyncio.run(
            on_pre_tool_call_checkpoint("write_file", {"file_path": "foo.py"})
        )
        assert result is None
        mock_create_task.assert_called_once()


def test_hook_fires_for_replace_in_file() -> None:
    with (
        patch("asyncio.create_task") as mock_create_task,
        patch(
            "code_muse.plugins.checkpointing.checkpoint_hook._create_checkpoint_async"
        ) as mock_checkpoint,
    ):
        mock_checkpoint.return_value = None
        result = asyncio.run(
            on_pre_tool_call_checkpoint("replace_in_file", {"file_path": "foo.py"})
        )
        assert result is None
        mock_create_task.assert_called_once()


def test_extract_affected_files_write_file() -> None:
    files = _extract_affected_files("write_file", {"file_path": "foo.py"})
    assert files == ["foo.py"]


def test_extract_affected_files_replace_in_file() -> None:
    files = _extract_affected_files("replace_in_file", {"file_path": "bar.py"})
    assert files == ["bar.py"]


def test_extract_affected_files_other_tool() -> None:
    files = _extract_affected_files("delete_file", {"file_path": "baz.py"})
    assert files == []
