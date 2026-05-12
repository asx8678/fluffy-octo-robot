"""Plan mode state management and tool registration.

Tools:
    - enter_plan_mode(goal: str = "")
    - exit_plan_mode()
    - get_plan_mode()
    - approve_plan()
    - open_plan_in_editor()
"""

import enum
import os
import subprocess
from pathlib import Path
from typing import Any

from pydantic_ai import RunContext

from code_muse.messaging.bus import get_message_bus


class PlanModeState(enum.Enum):
    """Three-state mode model."""

    DEFAULT = "default"
    AUTO_EDIT = "auto_edit"
    PLAN = "plan"


# Module-level mutable state (integration note: if the agent runtime ever
# exposes a formal ``_mode`` attribute, mirror state there).
_current_mode: PlanModeState = PlanModeState.DEFAULT
_plan_goal: str = ""


def get_current_mode() -> PlanModeState:
    """Return the active plan mode state."""
    return _current_mode


def get_plan_goal() -> str:
    """Return the current planning goal, if any."""
    return _plan_goal


def set_plan_mode(mode: PlanModeState, goal: str = "") -> None:
    """Update the global plan mode state and optional goal."""
    global _current_mode, _plan_goal
    _current_mode = mode
    _plan_goal = goal


def register_enter_plan_mode(agent: Any) -> None:
    """Register the ``enter_plan_mode`` tool on *agent*."""

    @agent.tool
    def enter_plan_mode(context: RunContext, goal: str = "") -> str:
        """Enter plan mode. Optional goal describes what you are planning.

        In plan mode, destructive tools (write_file, replace_in_file,
        delete_file, shell commands) are blocked. Research tools
        (read_file, list_files, grep, ask_user_question) remain available.
        """
        set_plan_mode(PlanModeState.PLAN, goal)
        bus = get_message_bus()
        bus.emit_info(f"📋 Plan mode activated{f' (goal: {goal})' if goal else ''}")
        return f"Plan mode active. Goal: {goal or '(none)'}"


def register_exit_plan_mode(agent: Any) -> None:
    """Register the ``exit_plan_mode`` tool on *agent*."""

    @agent.tool
    def exit_plan_mode(context: RunContext) -> str:
        """Exit plan mode and return to normal operation."""
        set_plan_mode(PlanModeState.DEFAULT)
        bus = get_message_bus()
        bus.emit_info("📋 Plan mode deactivated — normal editing resumed")
        return "Plan mode deactivated. Normal editing resumed."


def register_get_plan_mode(agent: Any) -> None:
    """Register the ``get_plan_mode`` tool on *agent*."""

    @agent.tool
    def get_plan_mode(context: RunContext) -> str:
        """Return the current plan mode state and goal."""
        mode = get_current_mode()
        goal = get_plan_goal()
        return f"Mode: {mode.value} | Goal: {goal or '(none)'}"


def register_approve_plan(agent: Any) -> None:
    """Register the ``approve_plan`` tool on *agent*."""

    @agent.tool
    def approve_plan(context: RunContext) -> str:
        """Approve the current plan and enter auto-edit mode."""
        set_plan_mode(PlanModeState.AUTO_EDIT)
        bus = get_message_bus()
        bus.emit_info("✅ Plan approved — entering auto-edit mode")
        return "Plan approved. Auto-edit mode active."


def register_open_plan_in_editor(agent: Any) -> None:
    """Register the ``open_plan_in_editor`` tool on *agent*."""

    @agent.tool
    def open_plan_in_editor(context: RunContext) -> str:
        """Open the most recent plan file in the default editor."""
        plans_dir = Path("plans")
        if not plans_dir.exists():
            return "Error: plans directory not found."

        plan_files = sorted(
            plans_dir.glob("*.md"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if not plan_files:
            return "Error: no plan files found."

        plan_path = plan_files[0]

        candidates = []
        editor = os.environ.get("EDITOR")
        if editor:
            candidates.append(editor)
        candidates.extend(["nvim", "vim", "nano"])

        for editor in candidates:
            try:
                subprocess.run([editor, str(plan_path)], check=False)
                return f"Opened {plan_path} in {editor}"
            except FileNotFoundError:
                continue

        return "Error: no suitable editor found (tried $EDITOR, nvim, vim, nano)."
