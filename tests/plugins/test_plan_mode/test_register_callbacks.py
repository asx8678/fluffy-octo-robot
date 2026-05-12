"""Tests for plan mode callback registration and slash commands."""

from unittest.mock import patch

import pytest

from code_muse.plugins.plan_mode.plan_mode_tools import PlanModeState, set_plan_mode
from code_muse.plugins.plan_mode.register_callbacks import (
    _handle_mode_command,
    _handle_plan_command,
    _on_custom_command,
    _on_custom_command_help,
    _register_plan_mode_tools,
)


@pytest.fixture(autouse=True)
def reset_plan_mode_state():
    set_plan_mode(PlanModeState.DEFAULT, "")
    yield
    set_plan_mode(PlanModeState.DEFAULT, "")


class TestRegisterPlanModeTools:
    def test_returns_five_tools(self):
        tools = _register_plan_mode_tools()
        assert len(tools) == 5
        names = {t["name"] for t in tools}
        assert names == {
            "enter_plan_mode",
            "exit_plan_mode",
            "get_plan_mode",
            "approve_plan",
            "open_plan_in_editor",
        }
        for t in tools:
            assert callable(t["register_func"])


class TestOnCustomCommandHelp:
    def test_returns_entries(self):
        entries = _on_custom_command_help()
        assert isinstance(entries, list)
        names = {e[0] for e in entries}
        assert "plan" in names
        assert "plan exit" in names
        assert "mode" in names


class TestHandlePlanCommand:
    def test_plan_no_goal(self):
        with patch(
            "code_muse.plugins.plan_mode.register_callbacks.emit_success"
        ) as mock_emit:
            result = _handle_plan_command("/plan")
            assert result is True
            mock_emit.assert_called_once_with("📋 Plan mode active")

    def test_plan_with_goal(self):
        with patch(
            "code_muse.plugins.plan_mode.register_callbacks.emit_success"
        ) as mock_emit:
            result = _handle_plan_command("/plan refactor auth module")
            assert result is True
            mock_emit.assert_called_once_with(
                "📋 Plan mode active — goal: refactor auth module"
            )

    def test_plan_exit(self):
        set_plan_mode(PlanModeState.PLAN, "some goal")
        with patch(
            "code_muse.plugins.plan_mode.register_callbacks.emit_success"
        ) as mock_emit:
            result = _handle_plan_command("/plan exit")
            assert result is True
            mock_emit.assert_called_once_with(
                "📋 Plan mode exited — normal editing resumed"
            )


class TestHandleModeCommand:
    def test_cycles_mode(self):
        set_plan_mode(PlanModeState.DEFAULT)
        with patch(
            "code_muse.plugins.plan_mode.register_callbacks.emit_info"
        ) as mock_emit:
            result = _handle_mode_command("/mode")
            assert result is True
            mock_emit.assert_called_once()
            args = mock_emit.call_args[0][0]
            assert "Mode changed" in args or "Mode cycled" in args


class TestOnCustomCommand:
    def test_handles_plan(self):
        result = _on_custom_command("/plan test", "plan")
        assert result is True

    def test_handles_plan_exit(self):
        result = _on_custom_command("/plan exit", "plan")
        assert result is True

    def test_handles_mode(self):
        result = _on_custom_command("/mode", "mode")
        assert result is True

    def test_ignores_other_commands(self):
        result = _on_custom_command("/foo", "foo")
        assert result is None
