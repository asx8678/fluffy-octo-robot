"""Callback registration for the Plan Mode plugin.

Registers:
    - ``enter_plan_mode``, ``exit_plan_mode``, ``get_plan_mode`` tools
    - ``pre_tool_call`` enforcement hook
    - ``/plan [goal]``, ``/plan exit`` slash commands
    - ``/mode`` slash command (delegated to :mod:`mode_cycling`)
    - Help entries for all slash commands
"""

import logging
from typing import Any

from code_muse.callbacks import register_callback
from code_muse.messaging import emit_info, emit_success
from code_muse.plugins.plan_mode.mode_cycling import cycle_mode
from code_muse.plugins.plan_mode.plan_hooks import plan_mode_pre_tool_call_hook
from code_muse.plugins.plan_mode.plan_mode_tools import (
    PlanModeState,
    get_current_mode,
    register_approve_plan,
    register_enter_plan_mode,
    register_exit_plan_mode,
    register_get_plan_mode,
    register_open_plan_in_editor,
    set_plan_mode,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tool registration callback
# ---------------------------------------------------------------------------


def _register_plan_mode_tools() -> list[dict[str, Any]]:
    """Return tool definitions for the plan mode plugin."""
    return [
        {"name": "enter_plan_mode", "register_func": register_enter_plan_mode},
        {"name": "exit_plan_mode", "register_func": register_exit_plan_mode},
        {"name": "get_plan_mode", "register_func": register_get_plan_mode},
        {"name": "approve_plan", "register_func": register_approve_plan},
        {"name": "open_plan_in_editor", "register_func": register_open_plan_in_editor},
    ]


# ---------------------------------------------------------------------------
# Slash-command handlers
# ---------------------------------------------------------------------------


def _on_custom_command(command: str, name: str) -> bool | None:
    """Handle ``/plan``, ``/plan exit``, and ``/mode`` commands."""
    if name == "mode":
        return _handle_mode_command(command)

    if name == "plan":
        return _handle_plan_command(command)

    return None


def _handle_plan_command(command: str) -> bool:
    """Handle ``/plan [goal]`` and ``/plan exit``."""
    parts = command.split(maxsplit=1)
    remainder = parts[1].strip() if len(parts) > 1 else ""

    if remainder.lower() == "exit":
        set_plan_mode(PlanModeState.DEFAULT)
        emit_success("📋 Plan mode exited — normal editing resumed")
        return True

    # remainder is the optional goal (may be empty)
    set_plan_mode(PlanModeState.PLAN, remainder)
    if remainder:
        emit_success(f"📋 Plan mode active — goal: {remainder}")
    else:
        emit_success("📋 Plan mode active")
    return True


def _handle_mode_command(command: str) -> bool:
    """Handle ``/mode`` — cycle through DEFAULT → AUTO_EDIT → PLAN."""
    old_mode = get_current_mode()
    new_mode = cycle_mode()
    mode_names = {
        PlanModeState.DEFAULT: "Default",
        PlanModeState.AUTO_EDIT: "Auto-edit",
        PlanModeState.PLAN: "Plan",
    }
    emit_info(
        f"🔁 Mode changed: {mode_names.get(old_mode, old_mode.value)} → "
        f"{mode_names.get(new_mode, new_mode.value)}"
    )
    return True


# ---------------------------------------------------------------------------
# Help entries
# ---------------------------------------------------------------------------


def _on_custom_command_help() -> list[tuple[str, str]]:
    return [
        ("plan", "Enter plan mode (optionally with a goal)"),
        ("plan exit", "Exit plan mode and resume normal editing"),
        ("mode", "Cycle through DEFAULT → AUTO_EDIT → PLAN mode"),
    ]


# ---------------------------------------------------------------------------
# Register all callbacks
# ---------------------------------------------------------------------------

register_callback("register_tools", _register_plan_mode_tools)
register_callback("pre_tool_call", plan_mode_pre_tool_call_hook)
register_callback("custom_command", _on_custom_command)
register_callback("custom_command_help", _on_custom_command_help)

logger.debug("Plan Mode plugin callbacks registered")
