"""Interactive mode loop for Muse."""

import asyncio
import os
import sys
from pathlib import Path

from code_muse.agents import get_current_agent
from code_muse.cli_runner.runner import _render_response, run_prompt_with_attachments
from code_muse.cli_runner.terminal_session import TerminalSession
from code_muse.cli_runner.input_disposition import (
    InputDisposition,
    InputDispositionKind,
    classify_input,
)
from code_muse.command_line.clipboard import get_clipboard_manager
from code_muse.command_line.shell_passthrough import (
    execute_shell_passthrough,
    is_shell_passthrough,
)
from code_muse.command_line.wiggum_state import (
    get_wiggum_prompt,
    increment_wiggum_count,
    is_wiggum_active,
    stop_wiggum,
)
from code_muse.config import (
    AUTOSAVE_DIR,
    COMMAND_HISTORY_FILE,
    auto_save_session_if_enabled,
    finalize_autosave_session,
    save_command_to_history,
)
from code_muse.messaging import (
    emit_error,
    emit_info,
    emit_success,
    emit_system_message,
    emit_warning,
)
from code_muse.terminal_utils import print_truecolor_warning


def _show_startup_info(display_console) -> None:
    """Display startup messages and terminal capability warnings."""
    emit_system_message("Type 'clear' to reset the conversation history.")
    emit_system_message(
        "Type @ for path completion, or /model to pick a model. "
        "Toggle multiline with Alt+M or F2; newline: Ctrl+J."
    )
    emit_system_message(
        "Use /autosave_load to manually load a previous autosave session."
    )
    emit_system_message(
        "Use /diff to configure diff highlighting colors for file changes."
    )
    # Print truecolor warning LAST so it's the most visible thing on startup
    # Big ugly red box should be impossible to miss! 🔴
    print_truecolor_warning(display_console)


async def _handle_initial_command(initial_command: str, agent, display_console) -> bool:
    """Process an initial command passed on the CLI before entering the main loop.

    Returns True if the initial command was fully handled, False otherwise.
    """
    if is_shell_passthrough(initial_command):
        execute_shell_passthrough(initial_command)
        return True

    emit_info(f"Processing initial command: {initial_command}")

    try:
        # Check if any tool is waiting for user input before showing spinner
        try:
            from code_muse.tools.command_runner import is_awaiting_user_input

            awaiting_input = is_awaiting_user_input()
        except ImportError:
            awaiting_input = False

        # Run with or without spinner based on whether we're awaiting input
        response, agent_task = await run_prompt_with_attachments(
            agent,
            initial_command,
            spinner_console=display_console,
            use_spinner=not awaiting_input,
        )
        if response is not None:
            agent_response = response.output

            # Update the agent's message history with the complete conversation
            # including the final assistant response
            if hasattr(response, "all_messages"):
                agent.set_message_history(list(response.all_messages()))

            # Emit structured message for proper markdown rendering
            from code_muse.messaging import get_message_bus
            from code_muse.messaging.messages import AgentResponseMessage

            response_msg = AgentResponseMessage(
                content=agent_response,
                is_markdown=True,
            )
            get_message_bus().emit(response_msg)

            emit_success("Continuing in Interactive Mode")
            emit_system_message(
                "Your command and response are preserved in the conversation history."
            )

    except Exception as e:
        emit_error(f"Error processing initial command: {str(e)}")
        return False

    return True


def _maybe_run_onboarding() -> None:
    """Run the onboarding tutorial on first startup if needed."""
    try:
        from code_muse.command_line.onboarding_wizard import should_show_onboarding

        if should_show_onboarding():
            import concurrent.futures

            from code_muse.command_line.onboarding_wizard import run_onboarding_wizard
            from code_muse.config import set_model_name

            # FREE-THREADED: ThreadPoolExecutor works with free-threaded Python 3.14.
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(lambda: asyncio.run(run_onboarding_wizard()))
                result = future.result(timeout=300)

            if result == "chatgpt":
                emit_info("🔐 Starting ChatGPT OAuth flow...")
                from code_muse.plugins.chatgpt_oauth.oauth_flow import run_oauth_flow

                run_oauth_flow()
                set_model_name("chatgpt-gpt-5.4")
            elif result == "claude":
                emit_info("🔐 Starting Claude Code OAuth flow...")
                from code_muse.plugins.claude_code_oauth.register_callbacks import (
                    _perform_authentication,
                )

                _perform_authentication()
                set_model_name("claude-code-claude-opus-4-7")
            elif result == "completed":
                emit_info("🎉 Tutorial complete! Happy coding!")
            elif result == "skipped":
                emit_info("⏭️ Tutorial skipped. Run /tutorial anytime!")
    except Exception as e:
        emit_warning(f"Tutorial auto-start failed: {e}")


async def _read_user_input(message_renderer, terminal_session) -> str:
    """Read user input via prompt_toolkit or fallback to basic input."""
    try:
        from code_muse.command_line.prompt_toolkit_completion import (
            get_input_with_combined_completion,
            get_prompt_with_active_model,
        )

        terminal_session.reset_before_input()
        task = await get_input_with_combined_completion(
            get_prompt_with_active_model(), history_file=COMMAND_HISTORY_FILE
        )
        terminal_session.ensure_ctrl_c_disabled()
        return task
    except ImportError:
        return input(">>> ")


def _handle_keyboard_interrupt(terminal_session) -> None:
    """Handle Ctrl+C during input by resetting terminal and stopping wiggum."""
    terminal_session.handle_interrupt()

    if is_wiggum_active():
        stop_wiggum()
        emit_warning("\n🍩 Wiggum loop stopped!")
    else:
        emit_warning("\nInput cancelled")


async def _cancel_agent_task_if_running(current_agent_task) -> None:
    """Cancel a running agent task and await its completion."""
    if current_agent_task and not current_agent_task.done():
        emit_info("Cancelling running agent task...")
        current_agent_task.cancel()
        try:  # noqa: SIM105
            await current_agent_task
        except asyncio.CancelledError:
            pass


async def _handle_eof() -> None:
    """Handle Ctrl+D by printing goodbye."""
    emit_success("\nGoodbye! (Ctrl+D)")


async def _run_main_input_loop(message_renderer, terminal_session):
    """Gather and process user input until a non-command task is ready."""
    while True:
        current_agent = get_current_agent()
        user_prompt = current_agent.get_user_prompt() or "Enter your coding task:"
        emit_info(f"{user_prompt}\n")

        try:
            task = await _read_user_input(message_renderer, terminal_session)
        except (KeyboardInterrupt, asyncio.CancelledError):
            _handle_keyboard_interrupt(terminal_session)
            continue
        except EOFError:
            await _handle_eof()
            return None

        disposition = classify_input(task)

        if disposition.kind == InputDispositionKind.SHELL:
            from code_muse.command_line.shell_passthrough import (
                execute_shell_passthrough,
            )
            execute_shell_passthrough(task)
            continue

        if disposition.kind == InputDispositionKind.EXIT:
            emit_success("Goodbye!")
            return None

        if disposition.kind == InputDispositionKind.CLEAR:
            agent = get_current_agent()
            new_session_id = finalize_autosave_session()
            agent.clear_message_history()
            emit_warning("Conversation history cleared!")
            emit_system_message("The agent will not remember previous interactions.")
            emit_info(f"Auto-save session rotated to: {new_session_id}")
            clipboard_manager = get_clipboard_manager()
            clipboard_count = clipboard_manager.get_pending_count()
            clipboard_manager.clear_pending()
            if clipboard_count > 0:
                emit_info(f"Cleared {clipboard_count} pending clipboard image(s)")
            continue

        if disposition.kind == InputDispositionKind.SLASH_HANDLED:
            continue

        # SLASH_REWRITE — check for special autosave-load sentinel
        if disposition.kind == InputDispositionKind.SLASH_REWRITE:
            prompt = disposition.prompt
            if prompt == "__AUTOSAVE_LOAD__":
                try:
                    from code_muse.command_line.autosave_menu import (
                        interactive_autosave_picker,
                    )
                    from code_muse.config import set_current_autosave_from_session_name
                    from code_muse.session_storage import (
                        load_session,
                        restore_autosave_interactively,
                    )

                    use_interactive_picker = (
                        sys.stdin.isatty() and sys.stdout.isatty()
                    )
                    if os.getenv("MUSE_NO_TUI") == "1":
                        use_interactive_picker = False

                    if use_interactive_picker:
                        chosen_session = await interactive_autosave_picker()
                        if not chosen_session:
                            emit_warning("Autosave load cancelled")
                            continue
                        base_dir = Path(AUTOSAVE_DIR)
                        history = load_session(chosen_session, base_dir)
                        agent = get_current_agent()
                        agent.set_message_history(history)
                        set_current_autosave_from_session_name(chosen_session)
                        total_tokens = sum(
                            agent.estimate_tokens_for_message(msg)
                            for msg in history
                        )
                        session_path = base_dir / f"{chosen_session}.json"
                        emit_success(
                            f"✅ Autosave loaded: {len(history)} messages "
                            f"({total_tokens} tokens)\n📁 From: {session_path}"
                        )
                        from code_muse.command_line.autosave_menu import (
                            display_resumed_history,
                        )
                        display_resumed_history(history)
                    else:
                        await restore_autosave_interactively(Path(AUTOSAVE_DIR))
                except Exception as e:
                    emit_error(f"Failed to load autosave: {e}")
                continue
            # Normal rewrite — fall through to task processing
            task = prompt

        # TASK — or rewritten task from SLASH_REWRITE
        if disposition.kind in (
            InputDispositionKind.TASK,
            InputDispositionKind.SLASH_REWRITE,
        ):
            if task.strip():
                save_command_to_history(task)
                return task

        # Shouldn't reach here, but if we do, loop again
        continue

def _handle_agent_cancellation(terminal_session) -> None:
    """Reset terminal state after an agent task is cancelled."""
    terminal_session.reset_before_input()
    terminal_session.ensure_ctrl_c_disabled()

    if is_wiggum_active():
        stop_wiggum()
        emit_warning("🍩 Wiggum loop stopped due to cancellation")


async def _render_and_autosave(result, current_agent, display_console) -> None:
    """Render agent response and autosave session."""
    _render_response(result, current_agent, display_console)
    # Brief pause to ensure all messages are rendered
    await asyncio.sleep(0.1)
    auto_save_session_if_enabled()


async def _wiggum_loop(current_agent, message_renderer, display_console):
    """Run the wiggum re-loop until it completes or is cancelled.

    Returns the current agent after the wiggum loop completes.
    """
    while is_wiggum_active():
        wiggum_prompt = get_wiggum_prompt()
        if not wiggum_prompt:
            stop_wiggum()
            break

        loop_num = increment_wiggum_count()
        emit_warning(f"\n🍩 WIGGUM RELOOPING! (Loop #{loop_num})")
        emit_system_message(f"Re-running prompt: {wiggum_prompt}")

        new_session_id = finalize_autosave_session()
        current_agent.clear_message_history()
        emit_system_message(f"Context cleared. Session rotated to: {new_session_id}")

        await asyncio.sleep(0.5)

        try:
            result, _ = await run_prompt_with_attachments(
                current_agent,
                wiggum_prompt,
                spinner_console=message_renderer.console,
            )

            if result is None:
                emit_warning("Wiggum loop cancelled by user")
                stop_wiggum()
                break

            await _render_and_autosave(result, current_agent, display_console)

        except KeyboardInterrupt:
            emit_warning("\n🍩 Wiggum loop interrupted by Ctrl+C")
            stop_wiggum()
            break
        except Exception as e:
            emit_error(f"Wiggum loop error: {e}")
            stop_wiggum()
            break

    return current_agent


async def interactive_mode(message_renderer, initial_command: str = None) -> None:
    """Run the agent in interactive mode."""

    display_console = message_renderer.console
    current_agent = get_current_agent()

    _show_startup_info(display_console)

    if initial_command:
        await _handle_initial_command(initial_command, current_agent, display_console)

    _maybe_run_onboarding()

    async with TerminalSession(display_console) as terminal_session:
        # Track the current agent task for cancellation on quit
        current_agent_task = None

        while True:
            task = await _run_main_input_loop(message_renderer, terminal_session)
            if task is None:
                await _cancel_agent_task_if_running(current_agent_task)
                break

            current_agent = get_current_agent()

            try:
                result, current_agent_task = await run_prompt_with_attachments(
                    current_agent,
                    task,
                    spinner_console=message_renderer.console,
                )
                if result is None:
                    _handle_agent_cancellation(terminal_session)
                    continue
                await _render_and_autosave(result, current_agent, display_console)
            except Exception:
                from code_muse.messaging.queue_console import get_queue_console

                get_queue_console().print_exception()
                auto_save_session_if_enabled()

            current_agent = await _wiggum_loop(
                current_agent, message_renderer, display_console
            )

            # Re-disable Ctrl+C after each iteration — various operations
            # may restore console mode. TerminalSession owns this concern.
            terminal_session.ensure_ctrl_c_disabled()
