"""Callback registration for the Task Complete Sound plugin.

Registers:
    - ``startup`` hook — reset nesting depth on app boot
    - ``agent_run_start`` / ``agent_run_end`` hooks — track nesting depth
      so sound only plays when the top-level run completes.
    - ``custom_command`` hook — ``/sound on|off|toggle|status|test|set|reset``
    - ``custom_command_help`` hook — help entries for ``/sound``
"""

import asyncio
import logging

from code_muse.callbacks import register_callback
from code_muse.messaging import emit_info, emit_success, emit_warning

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Nesting depth tracker — only play sound when outermost run finishes
# ---------------------------------------------------------------------------

_agent_depth: int = 0


# ---------------------------------------------------------------------------
# Startup hook — reset depth counter on app boot
# ---------------------------------------------------------------------------


def _on_startup() -> None:
    """Reset nesting depth counter on app boot."""
    global _agent_depth
    _agent_depth = 0
    logger.debug("Sound: plugin initialised, depth reset")


# ---------------------------------------------------------------------------
# Agent-run lifecycle hooks
# ---------------------------------------------------------------------------


async def _on_agent_run_start(
    agent_name: str,
    model_name: str,
    session_id: str | None = None,
) -> None:
    """Increment the nesting depth when any agent run starts."""
    global _agent_depth
    _agent_depth += 1
    logger.debug("Sound: agent run start — depth=%d agent=%s", _agent_depth, agent_name)


async def _on_agent_run_end(
    agent_name: str,
    model_name: str,
    session_id: str | None = None,
    success: bool = True,
    error: Exception | None = None,
    response_text: str | None = None,
    metadata: dict | None = None,
) -> None:
    """Play notification sound when the top-level agent run completes.

    Only fires when the nesting depth returns to zero (outermost run)
    and the run was successful.  Sound is fire-and-forget via
    ``asyncio.create_task`` so the hook returns immediately.
    """
    global _agent_depth
    _agent_depth = max(0, _agent_depth - 1)
    logger.debug(
        "Sound: agent run end — depth=%d agent=%s success=%s",
        _agent_depth,
        agent_name,
        success,
    )

    if _agent_depth > 0:
        return

    if not success:
        return

    from code_muse.plugins.task_complete_sound.config import is_sound_enabled

    if not is_sound_enabled():
        return

    # Fire-and-forget: don't block the agent_run_end event chain
    import contextlib

    from code_muse.plugins.task_complete_sound.sound_player import (
        play_notification,
    )

    with contextlib.suppress(RuntimeError):
        task = asyncio.get_running_loop().create_task(play_notification())
        task.add_done_callback(_log_task_exception)


# ---------------------------------------------------------------------------
# Slash commands: /sound on|off|toggle|status|test|set <path>|reset
# ---------------------------------------------------------------------------


def _log_task_exception(task: asyncio.Task) -> None:
    """Log exceptions from fire-and-forget sound tasks."""
    try:
        exc = task.exception()
    except asyncio.CancelledError, asyncio.InvalidStateError:
        return
    if exc is not None:
        logger.debug("Sound notification task failed: %s", exc)


async def _on_custom_command(command: str, name: str) -> bool | None:
    """Handle ``/sound`` slash commands."""
    if name != "sound":
        return None

    from code_muse.plugins.task_complete_sound.config import (
        get_sound_file,
        is_sound_enabled,
        set_sound_enabled,
        set_sound_file,
    )

    parts = command.split(maxsplit=2)
    sub = parts[1].strip().lower() if len(parts) > 1 else "status"

    # --- Toggle commands ---
    if sub == "on":
        set_sound_enabled(True)
        emit_success("🔔 Sound notifications enabled")
        return True

    if sub == "off":
        set_sound_enabled(False)
        emit_info("🔕 Sound notifications disabled")
        return True

    if sub == "toggle":
        current = is_sound_enabled()
        set_sound_enabled(not current)
        if not current:
            emit_success("🔔 Sound notifications enabled")
        else:
            emit_info("🔕 Sound notifications disabled")
        return True

    # --- Status command ---
    if sub == "status":
        enabled = is_sound_enabled()
        sound_file = get_sound_file()
        state = "enabled 🔔" if enabled else "disabled 🔇"
        file_info = (
            f"  Sound file: {sound_file}"
            if sound_file
            else "  Sound file: default beep"
        )
        emit_info(f"Sound notifications: {state}\n{file_info}")
        return True

    # --- Test command (awaited so user hears it) ---
    if sub == "test":
        from code_muse.plugins.task_complete_sound.sound_player import play_test

        emit_info("Playing test sound…")
        await play_test()
        return True

    # --- Set custom sound file ---
    if sub == "set":
        path = parts[2].strip() if len(parts) > 2 else ""
        if not path:
            emit_warning("Usage: /sound set /path/to/sound.wav")
            return True
        from pathlib import Path

        if not Path(path).is_file():
            emit_warning(f"File not found: {path}")
            return True
        set_sound_file(path)
        emit_success(f"🔔 Sound file set to: {path}")
        return True

    # --- Reset to default beep ---
    if sub == "reset":
        set_sound_file(None)
        emit_success("🔔 Sound file reset to default beep")
        return True

    # --- Unknown subcommand ---
    emit_info("Usage: /sound on|off|toggle|status|test|set <path>|reset")
    return True


def _on_custom_command_help() -> list[tuple[str, str]]:
    """Return help entries for the ``/sound`` command family."""
    return [
        ("sound on", "Enable sound notifications"),
        ("sound off", "Disable sound notifications"),
        ("sound toggle", "Toggle sound notifications on/off"),
        ("sound status", "Show sound notification status & file path"),
        ("sound test", "Play a test notification sound"),
        ("sound set <path>", "Set a custom sound file"),
        ("sound reset", "Reset sound file to default beep"),
    ]


# ---------------------------------------------------------------------------
# Register all callbacks
# ---------------------------------------------------------------------------

register_callback("startup", _on_startup)
register_callback("agent_run_start", _on_agent_run_start)
register_callback("agent_run_end", _on_agent_run_end)
register_callback("custom_command", _on_custom_command)
register_callback("custom_command_help", _on_custom_command_help)

logger.debug("Task Complete Sound plugin callbacks registered")
