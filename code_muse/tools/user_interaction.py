"""User interaction utilities (arrow selectors, approval prompts)."""

import asyncio
import sys
import time
from collections.abc import Callable

from prompt_toolkit import Application
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import Layout, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.text import Text

from code_muse.messaging import emit_error, emit_info, emit_success, emit_warning
from code_muse.tools.diff_formatting import format_diff_with_colors


async def arrow_select_async(
    message: str,
    choices: list[str],
    preview_callback: Callable[[int | None, str]] = None,
) -> str:
    """Async version: Show an arrow-key navigable selector with optional preview.

    Args:
        message: The prompt message to display
        choices: List of choice strings
        preview_callback: Optional callback that takes the selected index and returns
                         preview text to display below the choices

    Returns:
        The selected choice string

    Raises:
        KeyboardInterrupt: If user cancels with Ctrl-C
    """
    import html

    selected_index = [0]  # Mutable container for selected index
    result = [None]  # Mutable container for result

    def get_formatted_text():
        """Generate the formatted text for display."""
        # Escape XML special characters to prevent parsing errors
        safe_message = html.escape(message)
        lines = [f"<b>{safe_message}</b>", ""]
        for i, choice in enumerate(choices):
            safe_choice = html.escape(choice)
            if i == selected_index[0]:
                lines.append(f"<ansigreen>❯ {safe_choice}</ansigreen>")
            else:
                lines.append(f"  {safe_choice}")
        lines.append("")

        # Add preview section if callback provided
        if preview_callback is not None:
            preview_text = preview_callback(selected_index[0])
            if preview_text:
                import textwrap

                # Box width (excluding borders and padding)
                box_width = 60
                border_top = (
                    "<ansiyellow>┌─ Preview "
                    + "─" * (box_width - 10)
                    + "┐</ansiyellow>"
                )
                border_bottom = "<ansiyellow>└" + "─" * box_width + "┘</ansiyellow>"

                lines.append(border_top)

                # Wrap text to fit within box width (minus padding)
                wrapped_lines = textwrap.wrap(preview_text, width=box_width - 2)

                # If no wrapped lines (empty text), add empty line
                if not wrapped_lines:
                    wrapped_lines = [""]

                for wrapped_line in wrapped_lines:
                    safe_preview = html.escape(wrapped_line)
                    # Pad line to box width for consistent appearance
                    padded_line = safe_preview.ljust(box_width - 2)
                    lines.append(f"<dim>│ {padded_line} │</dim>")

                lines.append(border_bottom)
                lines.append("")

        lines.append(
            "<ansicyan>(Use ↑↓ or Ctrl+P/N to select, Enter to confirm)</ansicyan>"
        )
        return HTML("\n".join(lines))

    # Key bindings
    kb = KeyBindings()

    @kb.add("up")
    @kb.add("c-p")  # Ctrl+P = previous (Emacs-style)
    def move_up(event):
        selected_index[0] = (selected_index[0] - 1) % len(choices)
        event.app.invalidate()  # Force redraw to update preview

    @kb.add("down")
    @kb.add("c-n")  # Ctrl+N = next (Emacs-style)
    def move_down(event):
        selected_index[0] = (selected_index[0] + 1) % len(choices)
        event.app.invalidate()  # Force redraw to update preview

    @kb.add("enter")
    def accept(event):
        result[0] = choices[selected_index[0]]
        event.app.exit()

    @kb.add("c-c")  # Ctrl-C
    def cancel(event):
        result[0] = None
        event.app.exit()

    # Layout
    control = FormattedTextControl(get_formatted_text)
    layout = Layout(Window(content=control))

    # Application
    app = Application(
        layout=layout,
        key_bindings=kb,
        full_screen=False,
    )

    # Flush output before prompt_toolkit takes control
    sys.stdout.flush()
    sys.stderr.flush()

    # Run the app asynchronously
    await app.run_async()

    if result[0] is None:
        raise KeyboardInterrupt()

    return result[0]


def arrow_select(message: str, choices: list[str]) -> str:
    """Show an arrow-key navigable selector (synchronous version).

    Args:
        message: The prompt message to display
        choices: List of choice strings

    Returns:
        The selected choice string

    Raises:
        KeyboardInterrupt: If user cancels with Ctrl-C
    """

    selected_index = [0]  # Mutable container for selected index
    result = [None]  # Mutable container for result

    def get_formatted_text():
        """Generate the formatted text for display."""
        lines = [f"<b>{message}</b>", ""]
        for i, choice in enumerate(choices):
            if i == selected_index[0]:
                lines.append(f"<ansigreen>❯ {choice}</ansigreen>")
            else:
                lines.append(f"  {choice}")
        lines.append("")
        lines.append(
            "<ansicyan>(Use ↑↓ or Ctrl+P/N to select, Enter to confirm)</ansicyan>"
        )
        return HTML("\n".join(lines))

    # Key bindings
    kb = KeyBindings()

    @kb.add("up")
    @kb.add("c-p")  # Ctrl+P = previous (Emacs-style)
    def move_up(event):
        selected_index[0] = (selected_index[0] - 1) % len(choices)
        event.app.invalidate()  # Force redraw to update preview

    @kb.add("down")
    @kb.add("c-n")  # Ctrl+N = next (Emacs-style)
    def move_down(event):
        selected_index[0] = (selected_index[0] + 1) % len(choices)
        event.app.invalidate()  # Force redraw to update preview

    @kb.add("enter")
    def accept(event):
        result[0] = choices[selected_index[0]]
        event.app.exit()

    @kb.add("c-c")  # Ctrl-C
    def cancel(event):
        result[0] = None
        event.app.exit()

    # Layout
    control = FormattedTextControl(get_formatted_text)
    layout = Layout(Window(content=control))

    # Application
    app = Application(
        layout=layout,
        key_bindings=kb,
        full_screen=False,
    )

    # Flush output before prompt_toolkit takes control
    sys.stdout.flush()
    sys.stderr.flush()

    # Check if we're already in an async context
    try:
        asyncio.get_running_loop()
        # We're in an async context - can't use app.run()
        # Caller should use arrow_select_async instead
        raise RuntimeError(
            "arrow_select() called from async context. "
            "Use arrow_select_async() instead."
        )
    except RuntimeError as e:
        if "no running event loop" in str(e).lower():
            # No event loop, safe to use app.run()
            app.run()
        else:
            # Re-raise if it's our error message
            raise

    if result[0] is None:
        raise KeyboardInterrupt()

    return result[0]


def get_user_approval(
    title: str,
    content: Text | str,
    preview: str | None = None,
    border_style: str = "dim white",
    agent_name: str | None = None,
) -> tuple[bool, str | None]:
    """Show a beautiful approval panel with arrow-key selector.

    Args:
        title: Title for the panel (e.g., "File Operation", "Shell Command")
        content: Main content to display (Rich Text object or string)
        preview: Optional preview content (like a diff)
        border_style: Border color/style for the panel
        agent_name: Name of the assistant (defaults to config value)

    Returns:
        Tuple of (confirmed: bool, user_feedback: str | None)
        - confirmed: True if approved, False if rejected
        - user_feedback: Optional feedback text if user provided it
    """

    from code_muse.config import get_auto_approve
    from code_muse.tools.command_runner import set_awaiting_user_input

    if get_auto_approve():
        return True, None

    if agent_name is None:
        from code_muse.config import get_agent_name

        agent_name = get_agent_name().title()

    # Build panel content
    panel_content = Text(content) if isinstance(content, str) else content

    # Add preview if provided
    if preview:
        panel_content.append("\n\n", style="")
        panel_content.append("Preview of changes:", style="bold underline")
        panel_content.append("\n", style="")
        formatted_preview = format_diff_with_colors(preview)

        # Handle both string (text mode) and Text object (highlight mode)
        if isinstance(formatted_preview, Text):
            preview_text = formatted_preview
        else:
            preview_text = Text.from_markup(formatted_preview)

        panel_content.append(preview_text)

        # Mark that we showed a diff preview
        try:
            from code_muse.plugins.file_permission_handler.register_callbacks import (
                set_diff_already_shown,
            )

            set_diff_already_shown(True)
        except ImportError:
            pass

    # Create panel
    panel = Panel(
        panel_content,
        title=f"[bold white]{title}[/bold white]",
        border_style=border_style,
        padding=(1, 2),
    )

    # Pause spinners BEFORE showing panel
    set_awaiting_user_input(True)
    # Also explicitly pause spinners to ensure they're fully stopped
    try:
        from code_muse.messaging.spinner import pause_all_spinners

        pause_all_spinners()
    except Exception:
        pass

    time.sleep(0.3)  # Let spinners fully stop

    # Display panel
    local_console = Console()
    emit_info("")
    local_console.print(panel)
    emit_info("")

    # Flush and buffer before selector
    sys.stdout.flush()
    sys.stderr.flush()
    time.sleep(0.1)

    user_feedback = None
    confirmed = False

    try:
        # Final flush
        sys.stdout.flush()

        # Show arrow-key selector
        choice = arrow_select(
            "💭 What would you like to do?",
            [
                "✓ Approve",
                "✗ Reject",
                f"💬 Reject with feedback (tell {agent_name} what to change)",
            ],
        )

        if choice == "✓ Approve":
            confirmed = True
        elif choice == "✗ Reject":
            confirmed = False
        else:
            # User wants to provide feedback
            confirmed = False
            emit_info("")
            emit_info(f"Tell {agent_name} what to change:")
            user_feedback = Prompt.ask(
                "[bold green]➤[/bold green]",
                default="",
            ).strip()

            if not user_feedback:
                user_feedback = None

    except KeyboardInterrupt, EOFError:
        emit_error("Cancelled by user")
        confirmed = False

    finally:
        set_awaiting_user_input(False)

        # Force Rich console to reset display state to prevent artifacts
        try:
            # Clear Rich's internal display state to prevent artifacts
            local_console.file.write("\r")  # Return to start of line
            local_console.file.write("\x1b[K")  # Clear current line
            local_console.file.flush()
        except Exception:
            pass

        # Ensure streams are flushed
        sys.stdout.flush()
        sys.stderr.flush()

    # Show result BEFORE resuming spinners (no leftover distraction!)
    emit_info("")
    if not confirmed:
        if user_feedback:
            emit_error("Rejected with feedback!")
            emit_warning(f'Telling {agent_name}: "{user_feedback}"')
        else:
            emit_error("Rejected.")
    else:
        emit_success("Approved!")

    # NOW resume spinners after showing the result
    try:
        from code_muse.messaging.spinner import resume_all_spinners

        resume_all_spinners()
    except Exception:
        pass

    return confirmed, user_feedback


async def get_user_approval_async(
    title: str,
    content: Text | str,
    preview: str | None = None,
    border_style: str = "dim white",
    agent_name: str | None = None,
) -> tuple[bool, str | None]:
    """Async version of get_user_approval - show a beautiful approval panel
    with arrow-key selector.

    Args:
        title: Title for the panel (e.g., "File Operation", "Shell Command")
        content: Main content to display (Rich Text object or string)
        preview: Optional preview content (like a diff)
        border_style: Border color/style for the panel
        agent_name: Name of the assistant (defaults to config value)

    Returns:
        Tuple of (confirmed: bool, user_feedback: str | None)
        - confirmed: True if approved, False if rejected
        - user_feedback: Optional feedback text if user provided it
    """

    from code_muse.config import get_auto_approve
    from code_muse.tools.command_runner import set_awaiting_user_input

    if get_auto_approve():
        return True, None

    if agent_name is None:
        from code_muse.config import get_agent_name

        agent_name = get_agent_name().title()

    # Build panel content
    panel_content = Text(content) if isinstance(content, str) else content

    # Add preview if provided
    if preview:
        panel_content.append("\n\n", style="")
        panel_content.append("Preview of changes:", style="bold underline")
        panel_content.append("\n", style="")
        formatted_preview = format_diff_with_colors(preview)

        # Handle both string (text mode) and Text object (highlight mode)
        if isinstance(formatted_preview, Text):
            preview_text = formatted_preview
        else:
            preview_text = Text.from_markup(formatted_preview)

        panel_content.append(preview_text)

        # Mark that we showed a diff preview
        try:
            from code_muse.plugins.file_permission_handler.register_callbacks import (
                set_diff_already_shown,
            )

            set_diff_already_shown(True)
        except ImportError:
            pass

    # Create panel
    panel = Panel(
        panel_content,
        title=f"[bold white]{title}[/bold white]",
        border_style=border_style,
        padding=(1, 2),
    )

    # Pause spinners BEFORE showing panel
    set_awaiting_user_input(True)
    # Also explicitly pause spinners to ensure they're fully stopped
    try:
        from code_muse.messaging.spinner import pause_all_spinners

        pause_all_spinners()
    except Exception:
        pass

    await asyncio.sleep(0.3)  # Let spinners fully stop

    # Display panel
    local_console = Console()
    emit_info("")
    local_console.print(panel)
    emit_info("")

    # Flush and buffer before selector
    sys.stdout.flush()
    sys.stderr.flush()
    await asyncio.sleep(0.1)

    user_feedback = None
    confirmed = False

    try:
        # Final flush
        sys.stdout.flush()

        # Show arrow-key selector (ASYNC VERSION)
        choice = await arrow_select_async(
            "💭 What would you like to do?",
            [
                "✓ Approve",
                "✗ Reject",
                f"💬 Reject with feedback (tell {agent_name} what to change)",
            ],
        )

        if choice == "✓ Approve":
            confirmed = True
        elif choice == "✗ Reject":
            confirmed = False
        else:
            # User wants to provide feedback
            confirmed = False
            emit_info("")
            emit_info(f"Tell {agent_name} what to change:")
            user_feedback = Prompt.ask(
                "[bold green]➤[/bold green]",
                default="",
            ).strip()

            if not user_feedback:
                user_feedback = None

    except KeyboardInterrupt, EOFError:
        emit_error("Cancelled by user")
        confirmed = False

    finally:
        set_awaiting_user_input(False)

        # Force Rich console to reset display state to prevent artifacts
        try:
            # Clear Rich's internal display state to prevent artifacts
            local_console.file.write("\r")  # Return to start of line
            local_console.file.write("\x1b[K")  # Clear current line
            local_console.file.flush()
        except Exception:
            pass

        # Ensure streams are flushed
        sys.stdout.flush()
        sys.stderr.flush()

    # Show result BEFORE resuming spinners (no leftover distraction!)
    emit_info("")
    if not confirmed:
        if user_feedback:
            emit_error("Rejected with feedback!")
            emit_warning(f'Telling {agent_name}: "{user_feedback}"')
        else:
            emit_error("Rejected.")
    else:
        emit_success("Approved!")

    # NOW resume spinners after showing the result
    try:
        from code_muse.messaging.spinner import resume_all_spinners

        resume_all_spinners()
    except Exception:
        pass

    return confirmed, user_feedback
