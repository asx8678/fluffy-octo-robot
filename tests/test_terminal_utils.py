"""Comprehensive test coverage for terminal_utils.py.

Tests terminal utilities including:
- Unix terminal reset functionality
- Cross-platform terminal reset routing
- Truecolor support detection
- Terminal warning messages
"""

import os
import subprocess
from unittest.mock import MagicMock, patch

from code_muse.terminal_utils import (  # noqa: E402
    detect_truecolor_support,
    print_truecolor_warning,
    reset_terminal,
    reset_unix_terminal,
)


class TestUnixTerminalReset:
    """Test Unix/Linux/macOS terminal reset."""

    @patch("platform.system")
    @patch("subprocess.run")
    def test_reset_unix_terminal_success(self, mock_run, mock_platform):
        """Test successful Unix terminal reset."""
        mock_platform.return_value = "Darwin"  # macOS
        mock_run.return_value = MagicMock(returncode=0)

        reset_unix_terminal()

        mock_run.assert_called_once_with(["reset"], check=True, capture_output=True)

    @patch("platform.system")
    @patch("subprocess.run")
    def test_reset_unix_terminal_skips_windows(self, mock_run, mock_platform):
        """Test Unix reset does nothing on Windows."""
        mock_platform.return_value = "Windows"
        reset_unix_terminal()

        mock_run.assert_not_called()

    @patch("platform.system")
    @patch("subprocess.run")
    def test_reset_unix_terminal_handles_called_process_error(
        self, mock_run, mock_platform
    ):
        """Test Unix reset handles CalledProcessError gracefully."""
        mock_platform.return_value = "Linux"
        mock_run.side_effect = subprocess.CalledProcessError(1, "reset")

        # Should not raise exception
        reset_unix_terminal()

        mock_run.assert_called_once()

    @patch("platform.system")
    @patch("subprocess.run")
    def test_reset_unix_terminal_handles_file_not_found(self, mock_run, mock_platform):
        """Test Unix reset handles missing 'reset' command gracefully."""
        mock_platform.return_value = "Linux"
        mock_run.side_effect = FileNotFoundError()

        # Should not raise exception
        reset_unix_terminal()

        mock_run.assert_called_once()


class TestCrossPlatformReset:
    """Test cross-platform terminal reset routing."""

    @patch("platform.system")
    @patch("code_muse.terminal_utils.reset_windows_terminal_full")
    def test_reset_terminal_routes_to_windows(self, mock_win_reset, mock_platform):
        """Test reset routes to Windows function on Windows."""
        mock_platform.return_value = "Windows"

        reset_terminal()

        mock_win_reset.assert_called_once()

    @patch("platform.system")
    @patch("code_muse.terminal_utils.reset_unix_terminal")
    def test_reset_terminal_routes_to_unix(self, mock_unix_reset, mock_platform):
        """Test reset routes to Unix function on Unix-like systems."""
        mock_platform.return_value = "Linux"

        reset_terminal()

        mock_unix_reset.assert_called_once()

    @patch("platform.system")
    @patch("code_muse.terminal_utils.reset_unix_terminal")
    def test_reset_terminal_routes_to_unix_macos(self, mock_unix_reset, mock_platform):
        """Test reset routes to Unix function on macOS."""
        mock_platform.return_value = "Darwin"

        reset_terminal()

        mock_unix_reset.assert_called_once()



class TestTruecolorDetection:
    """Test truecolor support detection."""

    def test_detect_colorterm_truecolor(self):
        """Test detection via COLORTERM=truecolor."""
        with patch.dict(os.environ, {"COLORTERM": "truecolor"}):
            assert detect_truecolor_support() is True

    def test_detect_colorterm_24bit(self):
        """Test detection via COLORTERM=24bit."""
        with patch.dict(os.environ, {"COLORTERM": "24bit"}):
            assert detect_truecolor_support() is True

    def test_detect_xterm_direct(self):
        """Test detection via TERM=xterm-direct."""
        with patch.dict(os.environ, {"TERM": "xterm-direct"}):
            assert detect_truecolor_support() is True

    def test_detect_xterm_truecolor(self):
        """Test detection via TERM=xterm-truecolor."""
        with patch.dict(os.environ, {"TERM": "xterm-truecolor"}):
            assert detect_truecolor_support() is True

    def test_detect_iterm2(self):
        """Test detection via TERM=iterm2."""
        with patch.dict(os.environ, {"TERM": "iterm2"}):
            assert detect_truecolor_support() is True

    def test_detect_vte_256color(self):
        """Test detection via TERM=vte-256color."""
        with patch.dict(os.environ, {"TERM": "vte-256color"}):
            assert detect_truecolor_support() is True

    def test_detect_iterm_session_id(self):
        """Test detection via ITERM_SESSION_ID."""
        with patch.dict(os.environ, {"ITERM_SESSION_ID": "w0t0p0:123456"}):
            assert detect_truecolor_support() is True

    def test_detect_kitty_window_id(self):
        """Test detection via KITTY_WINDOW_ID."""
        with patch.dict(os.environ, {"KITTY_WINDOW_ID": "1"}):
            assert detect_truecolor_support() is True

    def test_detect_alacritty_socket(self):
        """Test detection via ALACRITTY_SOCKET."""
        with patch.dict(
            os.environ, {"ALACRITTY_SOCKET": "/tmp/Alacritty-12345.socket"}
        ):
            assert detect_truecolor_support() is True

    def test_detect_wt_session(self):
        """Test detection via WT_SESSION (Windows Terminal)."""
        with patch.dict(
            os.environ, {"WT_SESSION": "12345678-1234-1234-1234-123456789012"}
        ):
            assert detect_truecolor_support() is True

    def test_no_truecolor_support(self):
        """Test returns False when no indicators present."""
        with patch.dict(os.environ, {}, clear=True):
            # Mock Console.color_system to not be truecolor
            with patch("rich.console.Console") as mock_console_class:
                mock_console = MagicMock()
                mock_console.color_system = "standard"
                mock_console_class.return_value = mock_console

                assert detect_truecolor_support() is False


    def test_rich_fallback_256(self):
        """Test Rich fallback with 256 colors."""
        with patch.dict(os.environ, {}, clear=True):
            with patch("rich.console.Console") as mock_console_class:
                mock_console = MagicMock()
                mock_console.color_system = "256"
                mock_console_class.return_value = mock_console

                assert detect_truecolor_support() is False


    def test_case_insensitive_colorterm(self):
        """Test COLORTERM detection is case-insensitive."""
        with patch.dict(os.environ, {"COLORTERM": "TRUECOLOR"}):
            assert detect_truecolor_support() is True

        with patch.dict(os.environ, {"COLORTERM": "TrueColor"}):
            assert detect_truecolor_support() is True

    def test_partial_term_match(self):
        """Test TERM matching finds truecolor patterns anywhere."""
        with patch.dict(os.environ, {"TERM": "xterm-direct-256color"}):
            assert detect_truecolor_support() is True


class TestPrintTruecolorWarning:
    """Test truecolor warning printing."""


    def test_warning_with_rich(self):
        """Test warning printed with Rich when available."""
        with patch("code_muse.terminal_utils.detect_truecolor_support") as mock_detect:
            mock_detect.return_value = False

            mock_console = MagicMock()
            mock_console.color_system = "standard"

            with patch("rich.console.Console") as mock_console_class:
                mock_console_class.return_value = mock_console
                print_truecolor_warning()

                # Verify console was created and print was called
                mock_console_class.assert_called_once()
                mock_console.print.assert_called()

                # Verify warning content contains key phrases
                calls = mock_console.print.call_args_list
                call_args = [str(call) for call in calls]
                call_text = " ".join(call_args)
                assert "WARNING" in call_text or "truecolor" in call_text.lower()

    def test_warning_without_rich(self, capsys):
        """Test warning printed without Rich (fallback to plain print)."""
        with patch("code_muse.terminal_utils.detect_truecolor_support") as mock_detect:
            mock_detect.return_value = False

            # Make Console instantiation fail so the plain-print fallback runs.
            # Cython-compiled code bypasses sys.modules and builtins.__import__
            # monkeypatching, so we patch the class directly.
            def broken_console(*a, **k):
                raise ImportError("no rich")

            with patch("rich.console.Console", broken_console):
                print_truecolor_warning()

                captured = capsys.readouterr()
                assert "WARNING" in captured.out
                assert (
                    "truecolor" in captured.out.lower()
                    or "24-bit color" in captured.out
                )

    def test_warning_with_custom_console(self):
        """Test warning with provided console instance."""
        with patch("code_muse.terminal_utils.detect_truecolor_support") as mock_detect:
            mock_detect.return_value = False

            mock_console = MagicMock()
            mock_console.color_system = "standard"

            print_truecolor_warning(console=mock_console)

            # Verify provided console was used
            mock_console.print.assert_called()

    def test_warning_no_duplicate_calls(self):
        """Test warning only prints when truecolor is not supported."""
        with patch("code_muse.terminal_utils.detect_truecolor_support") as mock_detect:
            # First call - no truecolor, should print
            mock_detect.return_value = False
            with patch("rich.console.Console.print") as mock_print:
                print_truecolor_warning()
                first_call_count = mock_print.call_count

            # Second call - truecolor detected, should not print
            mock_detect.return_value = True
            with patch("rich.console.Console.print") as mock_print:
                print_truecolor_warning()
                mock_print.assert_not_called()

            assert first_call_count > 0  # Verify first call actually printed


class TestEdgeCasesAndIntegration:
    """Test edge cases and integration scenarios."""

    def test_reset_routing_based_on_platform(self):
        """Test that reset_terminal correctly routes based on platform."""
        # Test Windows routing
        with (
            patch("platform.system", return_value="Windows"),
            patch("code_muse.terminal_utils.reset_windows_terminal_full") as mock_win,
        ):
            reset_terminal()
            mock_win.assert_called_once()

        # Test Linux routing
        with patch("platform.system", return_value="Linux"):
            with patch("code_muse.terminal_utils.reset_unix_terminal") as mock_unix:
                reset_terminal()
                mock_unix.assert_called_once()

        # Test macOS routing
        with patch("platform.system", return_value="Darwin"):
            with patch("code_muse.terminal_utils.reset_unix_terminal") as mock_unix:
                reset_terminal()
                mock_unix.assert_called_once()

    def test_truecolor_detection_comprehensive(self):
        """Comprehensive truecolor detection with various environment combinations."""
        test_cases = [
            ({"COLORTERM": "truecolor"}, True),
            ({"COLORTERM": "24bit"}, True),
            ({"TERM": "xterm-direct"}, True),
            ({"TERM": "xterm-truecolor"}, True),
            ({"TERM": "iterm2"}, True),
            ({"TERM": "vte-256color"}, True),
            ({"ITERM_SESSION_ID": "w0t0p0:123"}, True),
            ({"KITTY_WINDOW_ID": "1"}, True),
            ({"ALACRITTY_SOCKET": "/tmp/alacritty.sock"}, True),
            ({"WT_SESSION": "1234-5678"}, True),
            ({"COLORTERM": "no"}, False),
            ({"TERM": "xterm-256color"}, False),
            ({}, False),
        ]

        for env_vars, expected in test_cases:
            with patch.dict(os.environ, env_vars, clear=True):
                # Mock Rich to return non-truecolor for fair testing
                with patch("rich.console.Console") as mock_console_class:
                    mock_console = MagicMock()
                    mock_console.color_system = "standard"
                    mock_console_class.return_value = mock_console

                    result = detect_truecolor_support()
                    assert result == expected, f"Failed for {env_vars}"

class TestANSISequenceFormats:
    """Test ANSI escape sequence formats used in the module."""

    def test_reset_sequence_format(self):
        """Test ANSI reset sequence has correct format."""
        reset_seq = "\x1b[0m"
        assert reset_seq.startswith("\x1b[")
        assert reset_seq.endswith("m")
        assert "0" in reset_seq
