"""Plan mode enforcement hook.

Registers a ``pre_tool_call`` callback that blocks destructive tools
according to the active plan mode state.
"""

import logging
from typing import Any

from code_muse.plugins.plan_mode.plan_mode_tools import PlanModeState, get_current_mode

logger = logging.getLogger(__name__)

# Tools allowed in PLAN mode (research / read-only / meta)
_PLAN_ALLOWED_TOOLS: set[str] = {
    "read_file",
    "list_files",
    "grep",
    "ask_user_question",
    "list_or_search_skills",
    "enter_plan_mode",
    "exit_plan_mode",
    "get_plan_mode",
    "approve_plan",
    "cancel_plan",
    "open_plan_in_editor",
}

# Tools blocked in AUTO_EDIT mode (shell commands only)
_AUTO_EDIT_BLOCKED_TOOLS: set[str] = {
    "agent_run_shell_command",
    "run_shell_command",
}


async def plan_mode_pre_tool_call_hook(
    tool_name: str, tool_args: dict, context: Any = None
) -> dict | None:
    """Enforce mode-specific tool restrictions.

    Returns:
        ``{"blocked": True, "error_message": "..."}`` if the tool is
        blocked in the current mode, otherwise ``None``.
    """
    mode = get_current_mode()

    if mode == PlanModeState.DEFAULT:
        return None

    if mode == PlanModeState.PLAN:
        if tool_name in _PLAN_ALLOWED_TOOLS:
            return None
        logger.info("Blocked tool '%s' during plan mode", tool_name)
        return {
            "blocked": True,
            "error_message": (
                "🚫 Plan mode is active. This tool is blocked during planning. "
                "Use exit_plan_mode to return to normal mode."
            ),
        }

    if mode == PlanModeState.AUTO_EDIT:
        if tool_name in _AUTO_EDIT_BLOCKED_TOOLS:
            logger.info("Blocked tool '%s' during auto-edit mode", tool_name)
            return {
                "blocked": True,
                "error_message": (
                    "🚫 Auto-edit mode is active. Shell commands are blocked. "
                    "Use exit_plan_mode to return to normal mode."
                ),
            }
        return None

    return None
