"""Additional coverage tests for terminal_utils.py.

These tests target truecolor detection and warning code paths
that are platform-independent.
"""

import sys
from unittest.mock import MagicMock, patch


class TestTruecolorDetectionEdgeCases:
    """Additional edge case tests for truecolor detection."""

    def test_detect_truecolor_rich_exception(self):
        """Test truecolor detection handles Rich exceptions."""
        import os

        with patch.dict(os.environ, {}, clear=True):
            with patch("rich.console.Console") as mock_console_class:
                mock_console_class.side_effect = Exception("Rich error")

                import importlib

                import code_muse.terminal_utils as tu

                importlib.reload(tu)

                result = tu.detect_truecolor_support()

                # Should return False when Rich fails
                assert result is False

    def test_detect_truecolor_colorterm_case_variations(self):
        """Test COLORTERM with various case variations."""
        import importlib
        import os

        import code_muse.terminal_utils as tu

        test_cases = [
            ("TRUECOLOR", True),
            ("24BIT", True),
            ("TrueColor", True),
            ("24Bit", True),
            ("other", False),
        ]

        for colorterm, expected in test_cases:
            with patch.dict(os.environ, {"COLORTERM": colorterm}, clear=True):
                with patch("rich.console.Console") as mock_console_class:
                    mock_console = MagicMock()
                    mock_console.color_system = "standard"
                    mock_console_class.return_value = mock_console

                    importlib.reload(tu)
                    result = tu.detect_truecolor_support()
                    assert result == expected, f"Failed for COLORTERM={colorterm}"


class TestPrintTruecolorWarningCodePaths:
    """Additional tests for print_truecolor_warning code paths."""

    def test_warning_with_provided_console(self):
        """Test warning uses provided console instance."""
        import code_muse.terminal_utils as tu

        mock_console = MagicMock()
        mock_console.color_system = "256"

        # Patch detect_truecolor_support on the already-loaded module
        with patch.object(tu, "detect_truecolor_support", return_value=False):
            tu.print_truecolor_warning(console=mock_console)

            # Console.print should have been called multiple times
            assert mock_console.print.call_count > 0

    def test_warning_creates_console_when_none_provided(self):
        """Test warning creates a console when None is provided."""
        import code_muse.terminal_utils as tu

        mock_console = MagicMock()
        mock_console.color_system = "standard"
        mock_console_class = MagicMock(return_value=mock_console)

        with patch.object(tu, "detect_truecolor_support", return_value=False):
            # Patch Console class at the point it's imported/used in the function
            with patch.dict(sys.modules):
                import rich.console

                original_console = rich.console.Console
                rich.console.Console = mock_console_class
                try:
                    tu.print_truecolor_warning(console=None)
                finally:
                    rich.console.Console = original_console

            # Verify console was created and print was called
            assert mock_console.print.call_count > 0

    def test_warning_skipped_when_truecolor_supported(self):
        """Test warning is completely skipped when truecolor is supported."""
        import code_muse.terminal_utils as tu

        mock_console = MagicMock()

        with patch.object(tu, "detect_truecolor_support", return_value=True):
            tu.print_truecolor_warning(console=mock_console)

            # Console.print should NOT be called
            mock_console.print.assert_not_called()

    def test_warning_fallback_to_print_when_rich_fails(self):
        """Test fallback to builtins.print when console creation fails."""
        import code_muse.terminal_utils as tu
        import rich.console

        with patch.object(tu, "detect_truecolor_support", return_value=False):
            # Make Console() raise ImportError to trigger fallback path.
            # Cython-compiled code bypasses builtins.print monkeypatching, so
            # we capture stdout instead.
            original_class = rich.console.Console
            rich.console.Console = MagicMock(side_effect=ImportError("No module"))
            try:
                import io
                import sys

                old_stdout = sys.stdout
                sys.stdout = captured = io.StringIO()
                try:
                    tu.print_truecolor_warning(console=None)
                finally:
                    sys.stdout = old_stdout
            finally:
                rich.console.Console = original_class

        captured_text = captured.getvalue()
        # Should have printed something via the fallback
        assert len(captured_text) > 0
        # Verify warning content
        lowered = captured_text.lower()
        assert "warning" in lowered or "truecolor" in lowered or "=" in lowered
