"""Terminal session context manager for interactive mode.

Manages prompt_toolkit setup, signal handler lifecycle, and terminal
reset — keeping _run_main_input_loop free of terminal state concerns.
"""

import signal
import sys

from code_muse.messaging import emit_error, emit_success, emit_warning
from code_muse.terminal_utils import (
    reset_windows_terminal_ansi,
    reset_windows_terminal_full,
)


class TerminalSession:
    """Async context manager for interactive terminal state.

    On enter: ensures prompt_toolkit, installs a protective SIGINT handler.
    On exit:  restores original SIGINT, resets terminal state.

    Provides helper methods so callers never touch terminal_utils directly.
    """

    def __init__(self, display_console):
        self.display_console = display_console
        self._original_sigint = None
        self._sigint_managed = False

    # ── Context manager protocol ────────────────────────────────────

    async def __aenter__(self):
        self._ensure_prompt_toolkit()
        self._setup_signal_handlers()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        self._restore_signal_handlers()
        self._reset_terminal()
        return False

    # ── Setup helpers (called on enter) ──────────────────────────────

    def _ensure_prompt_toolkit(self) -> None:
        """Ensure prompt_toolkit is installed, installing it if missing."""
        try:
            from code_muse.command_line.prompt_toolkit_completion import (
                get_input_with_combined_completion,  # noqa: F401
                get_prompt_with_active_model,  # noqa: F401
            )
        except ImportError:
            emit_warning("Warning: prompt_toolkit not installed. Installing now...")
            try:
                import subprocess

                subprocess.check_call(
                    [
                        sys.executable,
                        "-m",
                        "pip",
                        "install",
                        "--quiet",
                        "prompt_toolkit",
                    ]
                )
                emit_success("Successfully installed prompt_toolkit")
            except Exception as e:
                emit_error(f"Error installing prompt_toolkit: {e}")
                emit_warning("Falling back to basic input without tab completion")

    def _setup_signal_handlers(self) -> None:
        """Install a protective SIGINT handler scoped to this session."""
        self._original_sigint = signal.getsignal(signal.SIGINT)
        self._sigint_managed = True
        signal.signal(signal.SIGINT, self._sigint_handler)

    # ── Teardown helpers (called on exit) ────────────────────────────

    def _restore_signal_handlers(self) -> None:
        """Restore the SIGINT handler that was active before this session."""
        if self._sigint_managed and self._original_sigint is not None:
            signal.signal(signal.SIGINT, self._original_sigint)
            self._sigint_managed = False

    def _reset_terminal(self) -> None:
        """Reset terminal state on session exit."""
        reset_windows_terminal_ansi()
        self.ensure_ctrl_c_disabled()

    # ── SIGINT handler ───────────────────────────────────────────────

    def _sigint_handler(self, _sig, _frame):
        """Protective SIGINT handler for interactive mode."""
        reset_windows_terminal_full()
        self.ensure_ctrl_c_disabled()

    # ── Public helpers (replace scattered terminal_utils calls) ──────

    def reset_before_input(self) -> None:
        """Reset ANSI state before reading user input."""
        reset_windows_terminal_ansi()

    def ensure_ctrl_c_disabled(self) -> None:
        """Re-disable Ctrl+C after operations that may restore console mode."""
        try:
            from code_muse.terminal_utils import ensure_ctrl_c_disabled

            ensure_ctrl_c_disabled()
        except ImportError:
            pass

    def handle_interrupt(self) -> None:
        """Handle keyboard interrupt with full terminal reset."""
        reset_windows_terminal_full()
        self.ensure_ctrl_c_disabled()
