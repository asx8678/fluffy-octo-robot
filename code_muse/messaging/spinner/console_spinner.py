"""
Console spinner implementation for CLI mode using Rich's Live Display.
"""

import platform
import threading
import time

from rich.console import Console
from rich.live import Live
from rich.text import Text

from code_muse.config import get_animations_enabled
from code_muse.motion import MotionMode, shimmer_text

from .spinner_base import SpinnerBase


class ConsoleSpinner(SpinnerBase):
    """A console-based spinner implementation using Rich's Live Display."""

    def __init__(self, console=None):
        """Initialize the console spinner.

        Args:
            console: Optional Rich console instance to use for output.
                    If not provided, a new one will be created.
        """
        super().__init__()
        self.console = console or Console()
        self._thread = None
        self._stop_event = threading.Event()
        self._paused = False
        self._live = None
        self._animations_enabled = get_animations_enabled()
        self._debounce_timer = None

        # Register this spinner for global management
        from . import register_spinner

        register_spinner(self)

    def _do_start(self):
        """Actually create the Live display and start the update thread."""
        if not self._is_spinning:
            return
        # Print blank line before spinner for visual separation from content
        self.console.print()
        # Create a Live display for the spinner
        self._live = Live(
            self._generate_spinner_panel(),
            console=self.console,
            refresh_per_second=8,
            transient=True,  # Clear the spinner line when stopped (no residue left!)
            auto_refresh=False,  # Don't auto-refresh to avoid wiping out user input
        )
        self._live.start()
        # Start a thread to update the spinner frames
        self._thread = threading.Thread(target=self._update_spinner)
        self._thread.daemon = True
        self._thread.start()

    def start(self):
        """Start the spinner animation (debounced by 100 ms)."""
        # Cancel any pending debounce from a previous quick start/stop cycle
        if self._debounce_timer is not None:
            self._debounce_timer.cancel()
            self._debounce_timer = None

        super().start()
        self._stop_event.clear()

        # Don't start a new thread if one is already running
        if self._thread and self._thread.is_alive():
            return

        # Debounce: only start the live display if the spinner runs > 100 ms
        self._debounce_timer = threading.Timer(0.1, self._do_start)
        self._debounce_timer.daemon = True
        self._debounce_timer.start()

    def stop(self):
        """Stop the spinner animation."""
        # Cancel pending debounce so the spinner never appears for short calls
        if self._debounce_timer is not None:
            self._debounce_timer.cancel()
            self._debounce_timer = None

        if not self._is_spinning:
            return

        self._stop_event.set()
        self._is_spinning = False

        if self._live:
            self._live.stop()
            self._live = None

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=0.5)

        self._thread = None

        # Windows-specific cleanup: Rich's Live display can leave terminal in corrupted state
        if platform.system() == "Windows":
            import sys

            try:
                # Reset ANSI formatting for both stdout and stderr
                sys.stdout.write("\x1b[0m")  # Reset all attributes
                sys.stdout.flush()
                sys.stderr.write("\x1b[0m")
                sys.stderr.flush()

                # Clear the line and reposition cursor
                sys.stdout.write("\r")  # Return to start of line
                sys.stdout.write("\x1b[K")  # Clear to end of line
                sys.stdout.flush()

                # Flush keyboard input buffer to clear any stuck keys
                try:
                    import msvcrt

                    while msvcrt.kbhit():
                        msvcrt.getch()
                except ImportError:
                    pass  # msvcrt not available (not Windows or different Python impl)
            except Exception:
                pass  # Fail silently if cleanup doesn't work

        # Unregister this spinner from global management
        from . import unregister_spinner

        unregister_spinner(self)

    def update_frame(self):
        """Update to the next frame."""
        super().update_frame()

    def _generate_spinner_panel(self):
        """Generate a Rich panel containing the spinner text."""
        from code_muse.tools.command_runner import is_awaiting_user_input

        if self._paused or is_awaiting_user_input():
            return Text("")

        text = Text()

        motion_mode = MotionMode.from_animations_enabled(self._animations_enabled)

        if motion_mode == MotionMode.ANIMATED:
            # Use shimmer text — the highlight band sweeps across "Thinking..."
            thinking = Text("Thinking...")
            thinking.spans = shimmer_text("Thinking...", motion_mode)
            text.append(thinking)
        else:
            # Reduced motion: classic spinner frame
            text.append(SpinnerBase.THINKING_MESSAGE, style="bold green")
            text.append(self.current_frame, style="bold green")

        context_info = SpinnerBase.get_context_info()
        if context_info:
            text.append(" ")
            text.append(context_info, style="bold white")

        return text

    def _update_spinner(self):
        """Update the spinner in a background thread."""
        try:
            while not self._stop_event.is_set():
                # Update the frame
                self.update_frame()

                # Check if we're awaiting user input before updating the display
                from code_muse.tools.command_runner import is_awaiting_user_input

                awaiting_input = is_awaiting_user_input()

                # Update the live display only if not paused and not awaiting input
                if self._live and not self._paused and not awaiting_input:
                    # Manually refresh instead of auto-refresh to avoid wiping input
                    self._live.update(self._generate_spinner_panel())
                    self._live.refresh()

                # Short sleep to control animation speed
                time.sleep(0.12)
        except Exception as e:
            # Note: Using sys.stderr - can't use messaging during spinner
            import sys

            sys.stderr.write(f"\nSpinner error: {e}\n")
            self._is_spinning = False

    def pause(self):
        """Pause the spinner animation."""
        if not self._is_spinning:
            return
        self._paused = True
        # Cancel pending debounce so the spinner doesn't start while paused
        if self._debounce_timer is not None:
            self._debounce_timer.cancel()
            self._debounce_timer = None
        # Stop the live display completely to restore terminal echo during input
        if self._live:
            try:
                self._live.stop()
                self._live = None
                # Clear the line to remove any artifacts
                import sys

                sys.stdout.write("\r")  # Return to start of line
                sys.stdout.write("\x1b[K")  # Clear to end of line
                sys.stdout.flush()
            except Exception:
                pass

    def resume(self):
        """Resume the spinner animation."""
        # Check if we should show a spinner - don't resume if waiting for user input
        from code_muse.tools.command_runner import is_awaiting_user_input

        if is_awaiting_user_input():
            return  # Don't resume if waiting for user input

        if self._is_spinning and self._paused:
            self._paused = False
            # If the live display was never created (debounce or pause cancelled it),
            # restart the debounce timer rather than creating Live immediately.
            if not self._live and (self._thread is None or not self._thread.is_alive()):
                try:
                    import sys

                    sys.stdout.write("\r")
                    sys.stdout.write("\x1b[K")
                    sys.stdout.flush()
                except Exception:
                    pass
                self._debounce_timer = threading.Timer(0.1, self._do_start)
                self._debounce_timer.daemon = True
                self._debounce_timer.start()
                return
            # Restart the live display if it was stopped during pause
            if not self._live:
                try:
                    # Clear any leftover artifacts before starting
                    import sys

                    sys.stdout.write("\r")  # Return to start of line
                    sys.stdout.write("\x1b[K")  # Clear to end of line
                    sys.stdout.flush()

                    # Print blank line before spinner for visual separation
                    self.console.print()

                    self._live = Live(
                        self._generate_spinner_panel(),
                        console=self.console,
                        refresh_per_second=8,
                        transient=True,  # Clear spinner line when stopped
                        auto_refresh=False,
                    )
                    self._live.start()
                except Exception:
                    pass
            else:
                # If live display still exists, clear console state first
                try:
                    # Force Rich to reset any cached console state
                    if hasattr(self.console, "_buffer"):
                        # Clear Rich's internal buffer to prevent artifacts
                        self.console.file.write("\r")  # Return to start
                        self.console.file.write("\x1b[K")  # Clear line
                        self.console.file.flush()

                    self._live.update(self._generate_spinner_panel())
                    self._live.refresh()
                except Exception:
                    pass

    def __enter__(self):
        """Support for context manager."""
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Clean up when exiting context manager."""
        self.stop()
