"""Additional coverage tests for code_muse.command_line.utils.

Focuses on _reset_windows_console and safe_input functions
that require platform-specific mocking.
"""

import sys
from unittest.mock import MagicMock, patch

import pytest


class TestResetWindowsConsole:
    """Tests for _reset_windows_console function."""

    def test_returns_early_on_darwin(self):
        """On macOS (darwin), function returns immediately."""
        from code_muse.command_line.utils import _reset_windows_console

        with patch.object(sys, "platform", "darwin"):
            result = _reset_windows_console()
            assert result is None

    def test_silently_ignores_exceptions(self):
        """On Windows, exceptions are silently ignored."""
        from code_muse.command_line.utils import _reset_windows_console

        # Create a mock that raises an exception
        mock_ctypes = MagicMock()
        mock_ctypes.windll.kernel32.GetStdHandle.side_effect = Exception("test error")

        with patch.object(sys, "platform", "win32"):
            with patch.dict("sys.modules", {"ctypes": mock_ctypes}):
                # Should not raise - errors are silently caught
                result = _reset_windows_console()
                assert result is None


class TestSafeInput:
    """Tests for safe_input function."""

    def test_returns_stripped_input(self):
        """safe_input should return stripped input."""
        from code_muse.command_line.utils import safe_input

        with patch("code_muse.command_line.utils._reset_windows_console"):
            with patch("builtins.input", return_value="  hello world  "):
                result = safe_input()
                assert result == "hello world"

    def test_returns_empty_string_for_empty_input(self):
        """safe_input should return empty string for empty input."""
        from code_muse.command_line.utils import safe_input

        with patch("code_muse.command_line.utils._reset_windows_console"):
            with patch("builtins.input", return_value=""):
                result = safe_input()
                assert result == ""

    def test_returns_empty_string_for_whitespace_only(self):
        """safe_input should return empty string for whitespace-only input."""
        from code_muse.command_line.utils import safe_input

        with patch("code_muse.command_line.utils._reset_windows_console"):
            with patch("builtins.input", return_value="   "):
                result = safe_input()
                assert result == ""

    def test_passes_prompt_to_input(self):
        """safe_input should pass prompt text to input()."""
        from code_muse.command_line.utils import safe_input

        with patch("code_muse.command_line.utils._reset_windows_console"):
            with patch("builtins.input", return_value="test") as mock_input:
                safe_input("Enter value: ")
                mock_input.assert_called_once_with("Enter value: ")

    def test_propagates_keyboard_interrupt(self):
        """safe_input should propagate KeyboardInterrupt."""
        from code_muse.command_line.utils import safe_input

        with patch("code_muse.command_line.utils._reset_windows_console"):
            with patch("builtins.input", side_effect=KeyboardInterrupt):
                with pytest.raises(KeyboardInterrupt):
                    safe_input()

    def test_propagates_eof_error(self):
        """safe_input should propagate EOFError."""
        from code_muse.command_line.utils import safe_input

        with patch("code_muse.command_line.utils._reset_windows_console"):
            with patch("builtins.input", side_effect=EOFError):
                with pytest.raises(EOFError):
                    safe_input()

    def test_default_empty_prompt(self):
        """safe_input should use empty prompt by default."""
        from code_muse.command_line.utils import safe_input

        with patch("code_muse.command_line.utils._reset_windows_console"):
            with patch("builtins.input", return_value="test") as mock_input:
                safe_input()
                mock_input.assert_called_once_with("")
