"""Tests for plan mode pre_tool_call enforcement hook."""

import pytest

from code_muse.plugins.plan_mode.plan_hooks import plan_mode_pre_tool_call_hook
from code_muse.plugins.plan_mode.plan_mode_tools import PlanModeState, set_plan_mode


@pytest.fixture(autouse=True)
def reset_plan_mode_state():
    set_plan_mode(PlanModeState.DEFAULT)
    yield
    set_plan_mode(PlanModeState.DEFAULT)


class TestPlanModePreToolCallHook:
    async def test_not_in_plan_mode_allows_all(self):
        set_plan_mode(PlanModeState.DEFAULT)
        result = await plan_mode_pre_tool_call_hook("write_file", {"path": "x.py"})
        assert result is None

    async def test_allowed_tools_pass_in_plan_mode(self):
        set_plan_mode(PlanModeState.PLAN)
        allowed = [
            "read_file",
            "list_files",
            "grep",
            "ask_user_question",
            "list_or_search_skills",
            "enter_plan_mode",
            "exit_plan_mode",
            "get_plan_mode",
        ]
        for tool in allowed:
            result = await plan_mode_pre_tool_call_hook(tool, {})
            assert result is None, f"{tool} should be allowed in plan mode"

    async def test_blocked_tools_are_blocked_in_plan_mode(self):
        set_plan_mode(PlanModeState.PLAN)
        blocked = [
            "create_file",
            "write_file",
            "replace_in_file",
            "delete_file",
            "delete_snippet",
            "agent_run_shell_command",
            "run_shell_command",
        ]
        for tool in blocked:
            result = await plan_mode_pre_tool_call_hook(tool, {})
            assert isinstance(result, dict)
            assert result.get("blocked") is True
            assert "Plan mode is active" in result.get("error_message", "")

    async def test_unknown_tools_blocked_in_plan_mode(self):
        set_plan_mode(PlanModeState.PLAN)
        result = await plan_mode_pre_tool_call_hook("some_future_tool", {})
        assert isinstance(result, dict)
        assert result.get("blocked") is True
        assert "Plan mode is active" in result.get("error_message", "")

    async def test_auto_edit_mode_allows_file_editing(self):
        set_plan_mode(PlanModeState.AUTO_EDIT)
        result = await plan_mode_pre_tool_call_hook("replace_in_file", {"path": "x.py"})
        assert result is None

    async def test_auto_edit_mode_blocks_shell_commands(self):
        set_plan_mode(PlanModeState.AUTO_EDIT)
        for tool in ("agent_run_shell_command", "run_shell_command"):
            result = await plan_mode_pre_tool_call_hook(tool, {"command": "ls"})
            assert isinstance(result, dict)
            assert result.get("blocked") is True
            assert "Auto-edit mode is active" in result.get("error_message", "")
