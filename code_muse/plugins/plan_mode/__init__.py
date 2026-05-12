"""Plan Mode plugin for Muse.

Provides tools and hooks to enter/exit a planning-only mode where
destructive tools (write, replace, delete, shell) are blocked while
research tools (read, list, grep, ask) remain available.
"""

from code_muse.plugins.plan_mode.mode_cycling import cycle_mode
from code_muse.plugins.plan_mode.plan_generation import generate_plan_md, save_plan
from code_muse.plugins.plan_mode.plan_hooks import plan_mode_pre_tool_call_hook
from code_muse.plugins.plan_mode.plan_mode_tools import (
    PlanModeState,
    get_current_mode,
    get_plan_goal,
    register_approve_plan,
    register_enter_plan_mode,
    register_exit_plan_mode,
    register_get_plan_mode,
    register_open_plan_in_editor,
    set_plan_mode,
)

__all__ = [
    "PlanModeState",
    "get_current_mode",
    "get_plan_goal",
    "set_plan_mode",
    "register_enter_plan_mode",
    "register_exit_plan_mode",
    "register_get_plan_mode",
    "register_approve_plan",
    "register_open_plan_in_editor",
    "generate_plan_md",
    "save_plan",
    "cycle_mode",
    "plan_mode_pre_tool_call_hook",
]
