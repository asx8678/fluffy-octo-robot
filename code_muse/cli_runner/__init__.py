"""CLI runner for Muse.

Contains the main application logic, interactive mode, and entry point.
"""

# Apply pydantic-ai patches BEFORE any pydantic-ai imports
from code_muse.pydantic_patches import apply_all_patches

apply_all_patches()

import asyncio
import contextlib
import os
import sys
import traceback

from rich.console import Console

from code_muse import __version__, callbacks, plugins
from code_muse.agents import get_available_agents, set_current_agent
from code_muse.cli_runner.args import build_parser
from code_muse.cli_runner.loop import interactive_mode
from code_muse.cli_runner.resume import _resume_session_from_path
from code_muse.cli_runner.runner import (
    execute_single_prompt,
    run_prompt_with_attachments,
)
from code_muse.config import ensure_config_exists, initialize_command_history_file
from code_muse.http_utils import find_available_port
from code_muse.keymap import KeymapError, validate_cancel_agent_key
from code_muse.messaging import emit_error, emit_system_message
from code_muse.terminal_utils import reset_unix_terminal, reset_windows_terminal_full
from code_muse.version_checker import default_version_mismatch_behavior

__all__ = [
    "interactive_mode",
    "execute_single_prompt",
    "run_prompt_with_attachments",
    "main",
    "main_entry",
]


async def main():
    """Main async entry point for Muse CLI."""
    parser = build_parser()
    args = parser.parse_args()

    # Load plugins after arg parsing (not at module level — avoids eager import-time side effects)
    plugins.load_plugin_callbacks()

    # Set verbosity level from CLI flags (no sys.argv scan — args are parsed above)
    if args.ultra_compact:
        pass
    elif args.verbose:
        pass  # TODO: wire verbosity level (see issue dxe)

    from code_muse.messaging import (
        RichConsoleRenderer,
        get_message_bus,
    )

    # Create a shared console for the bus renderer
    display_console = Console()

    # Single renderer backed by the new MessageBus
    message_bus = get_message_bus()
    message_renderer = RichConsoleRenderer(message_bus, display_console)
    message_renderer.start()

    initialize_command_history_file()

    # ── Launch banner ──────────────────────────────────────────────────
    # Show the beautiful Muse ASCII art when entering interactive mode
    if not args.prompt:
        from code_muse.banner import render_banner

        render_banner(display_console)

        # Truecolor warning moved to interactive_mode() so it prints LAST
        # after all the help stuff - max visibility for the ugly red box!

    available_port = await asyncio.to_thread(find_available_port)
    if available_port is None:
        emit_error("No available ports in range 8090-9010!")
        return

    # Early model setting if specified via command line
    # This happens before ensure_config_exists() to ensure config is set up correctly
    early_model = None
    if args.model:
        early_model = args.model.strip()
        from code_muse.config import set_model_name

        set_model_name(early_model)

    ensure_config_exists()

    # Validate cancel_agent_key configuration early
    try:
        validate_cancel_agent_key()
    except KeymapError as e:
        emit_error(str(e))
        sys.exit(1)

    # Show uvx detection notice if we're on Windows + uvx
    # Also disable Ctrl+C at the console level to prevent terminal bricking
    try:
        from code_muse.uvx_detection import should_use_alternate_cancel_key

        if should_use_alternate_cancel_key():
            from code_muse.terminal_utils import (
                disable_windows_ctrl_c,
                set_keep_ctrl_c_disabled,
            )

            # Disable Ctrl+C at the console input level
            # This prevents Ctrl+C from being processed as a signal at all
            disable_windows_ctrl_c()

            # Set flag to keep it disabled (prompt_toolkit may re-enable it)
            set_keep_ctrl_c_disabled(True)

            # Use print directly - emit_system_message can get cleared by ANSI codes
            print(
                "🔧 Detected uvx launch on Windows - using Ctrl+K for cancellation "
                "(Ctrl+C is disabled to prevent terminal issues)"
            )

            # Also install a SIGINT handler as backup
            import signal

            def _uvx_protective_sigint_handler(_sig, _frame):
                """Protective SIGINT handler for Windows+uvx."""
                reset_windows_terminal_full()
                # Re-disable Ctrl+C in case something re-enabled it
                disable_windows_ctrl_c()

            signal.signal(signal.SIGINT, _uvx_protective_sigint_handler)
    except ImportError:
        pass  # uvx_detection module not available, ignore

    # Load API keys from muse.cfg into environment variables
    from code_muse.config import load_api_keys_to_environment

    load_api_keys_to_environment()

    # Handle model validation from command line
    # (validation happens here, setting was earlier)
    if args.model:
        from code_muse.config import _validate_model_exists

        model_name = args.model.strip()
        try:
            # Validate that the model exists in models.json
            if not _validate_model_exists(model_name):
                from code_muse.model_factory import ModelFactory

                models_config = ModelFactory.load_config()
                available_models = list(models_config.keys()) if models_config else []

                emit_error(f"Model '{model_name}' not found")
                emit_system_message(f"Available models: {', '.join(available_models)}")
                sys.exit(1)

            # Model is valid, show confirmation (already set earlier)
            emit_system_message(f"🎯 Using model: {model_name}")
        except Exception as e:
            emit_error(f"Error validating model: {str(e)}")
            sys.exit(1)

    # Handle agent selection from command line
    if args.agent:
        agent_name = args.agent.lower()
        try:
            # First check if the agent exists by getting available agents
            available_agents = get_available_agents()
            if agent_name not in available_agents:
                emit_error(f"Agent '{agent_name}' not found")
                emit_system_message(
                    f"Available agents: {', '.join(available_agents.keys())}"
                )
                sys.exit(1)

            # Agent exists, set it
            set_current_agent(agent_name)
            emit_system_message(f"🤖 Using agent: {agent_name}")
        except Exception as e:
            emit_error(f"Error setting agent: {str(e)}")
            sys.exit(1)

    current_version = __version__

    no_version_update = os.getenv("NO_VERSION_UPDATE", "").lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
    if no_version_update:
        version_msg = f"Current version: {current_version}"
        update_disabled_msg = (
            "Update phase disabled because NO_VERSION_UPDATE is set to 1 or true"
        )
        emit_system_message(version_msg)
        emit_system_message(update_disabled_msg)
    else:
        if len(callbacks.get_callbacks("version_check")):
            await callbacks.on_version_check(current_version)
        else:
            await default_version_mismatch_behavior(current_version)

    await callbacks.on_startup()

    if args.resume:
        _resume_session_from_path(
            args.resume, allow_legacy=args.import_legacy_pickle_session
        )

    try:
        initial_command = None
        prompt_only_mode = False

        if args.prompt:
            initial_command = args.prompt
            prompt_only_mode = True
        elif args.command:
            initial_command = " ".join(args.command)
            prompt_only_mode = False

        if prompt_only_mode:
            await execute_single_prompt(initial_command, message_renderer)
        else:
            # Default to interactive mode (no args = same as -i)
            await interactive_mode(message_renderer, initial_command=initial_command)
    finally:
        if message_renderer:
            message_renderer.stop()
        await callbacks.on_shutdown()


def main_entry():
    """Entry point for the installed CLI tool."""
    exit_code = 0
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        # Note: Using sys.stderr for crash output -
        # messaging system may not be available
        sys.stderr.write(traceback.format_exc())
        exit_code = 130  # Standard SIGINT exit code
    finally:
        # Explicitly shut down subsystems before the process exits.
        # The atexit hooks provide a safety net, but calling them
        # here ensures orderly cleanup even if daemon threads keep
        # the interpreter alive briefly after asyncio.run() returns.
        try:
            from code_muse.tools import command_runner

            command_runner.shutdown()
        except Exception:
            pass
        with contextlib.suppress(Exception):
            callbacks._shutdown_executor()
        # Reset terminal on Unix-like systems (not Windows)
        reset_unix_terminal()
    return exit_code
