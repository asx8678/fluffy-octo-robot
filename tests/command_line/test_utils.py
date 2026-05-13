"""Tests for command_line/utils.py - 100% coverage."""

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from code_muse.command_line.utils import (
    list_directory,
    make_directory_table,
    safe_input,
)


class TestListDirectory:
    def test_default_cwd(self):
        dirs, files = list_directory()
        # Should return something from cwd
        assert isinstance(dirs, list)
        assert isinstance(files, list)

    def test_specific_path(self):
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "subdir").mkdir(parents=True)
            (Path(td) / "file.txt").write_text("x")
            dirs, files = list_directory(td)
            assert "subdir" in dirs
            assert "file.txt" in files

    def test_error(self):
        with pytest.raises(RuntimeError, match="Error listing directory"):
            list_directory("/nonexistent_path_xyz_abc")


class TestMakeDirectoryTable:
    def test_default(self):
        table = make_directory_table()
        assert table is not None

    def test_specific_path(self):
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "adir").mkdir(parents=True)
            (Path(td) / "afile").write_text("")
            table = make_directory_table(td)
            assert table is not None


class TestSafeInput:
    @patch("code_muse.command_line.utils._reset_windows_console")
    @patch("builtins.input", return_value="  hello  ")
    def test_strips_input(self, mock_input, mock_reset):
        result = safe_input("prompt> ")
        assert result == "hello"
        mock_reset.assert_called_once()

    @patch("code_muse.command_line.utils._reset_windows_console")
    @patch("builtins.input", return_value="")
    def test_empty_input(self, mock_input, mock_reset):
        result = safe_input()
        assert result == ""
