"""Tests for plan mode tools (enter, exit, get)."""

from unittest.mock import MagicMock, patch

import pytest

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


@pytest.fixture(autouse=True)
def reset_plan_mode_state():
    """Reset global plan mode state before each test."""
    set_plan_mode(PlanModeState.DEFAULT, "")
    yield
    set_plan_mode(PlanModeState.DEFAULT, "")


class MockAgent:
    """Minimal mock agent that captures registered tools."""

    def __init__(self):
        self.tools: dict[str, callable] = {}

    def tool(self, fn):
        self.tools[fn.__name__] = fn
        return fn


class TestRegisterEnterPlanMode:
    def test_registers_tool(self):
        agent = MockAgent()
        register_enter_plan_mode(agent)
        assert "enter_plan_mode" in agent.tools

    def test_tool_sets_plan_mode(self):
        agent = MockAgent()
        register_enter_plan_mode(agent)
        tool = agent.tools["enter_plan_mode"]
        mock_ctx = MagicMock()
        result = tool(mock_ctx, goal="refactor auth")
        assert get_current_mode() == PlanModeState.PLAN
        assert get_plan_goal() == "refactor auth"
        assert "Plan mode active" in result

    def test_tool_emits_ui_message(self):
        agent = MockAgent()
        register_enter_plan_mode(agent)
        tool = agent.tools["enter_plan_mode"]
        mock_ctx = MagicMock()
        with patch(
            "code_muse.plugins.plan_mode.plan_mode_tools.get_message_bus"
        ) as mock_bus:
            mock_instance = MagicMock()
            mock_bus.return_value = mock_instance
            tool(mock_ctx, goal="test goal")
            mock_instance.emit_info.assert_called_once()


class TestRegisterExitPlanMode:
    def test_registers_tool(self):
        agent = MockAgent()
        register_exit_plan_mode(agent)
        assert "exit_plan_mode" in agent.tools

    def test_tool_resets_to_default(self):
        set_plan_mode(PlanModeState.PLAN, "some goal")
        agent = MockAgent()
        register_exit_plan_mode(agent)
        tool = agent.tools["exit_plan_mode"]
        mock_ctx = MagicMock()
        result = tool(mock_ctx)
        assert get_current_mode() == PlanModeState.DEFAULT
        assert get_plan_goal() == ""
        assert "deactivated" in result


class TestRegisterGetPlanMode:
    def test_registers_tool(self):
        agent = MockAgent()
        register_get_plan_mode(agent)
        assert "get_plan_mode" in agent.tools

    def test_tool_returns_current_state(self):
        set_plan_mode(PlanModeState.PLAN, "migrate db")
        agent = MockAgent()
        register_get_plan_mode(agent)
        tool = agent.tools["get_plan_mode"]
        mock_ctx = MagicMock()
        result = tool(mock_ctx)
        assert "plan" in result
        assert "migrate db" in result


class TestRegisterApprovePlan:
    def test_registers_tool(self):
        agent = MockAgent()
        register_approve_plan(agent)
        assert "approve_plan" in agent.tools

    def test_tool_transitions_to_auto_edit(self):
        set_plan_mode(PlanModeState.PLAN, "some goal")
        agent = MockAgent()
        register_approve_plan(agent)
        tool = agent.tools["approve_plan"]
        mock_ctx = MagicMock()
        result = tool(mock_ctx)
        assert get_current_mode() == PlanModeState.AUTO_EDIT
        assert "approved" in result.lower()

    def test_tool_emits_ui_message(self):
        agent = MockAgent()
        register_approve_plan(agent)
        tool = agent.tools["approve_plan"]
        mock_ctx = MagicMock()
        with patch(
            "code_muse.plugins.plan_mode.plan_mode_tools.get_message_bus"
        ) as mock_bus:
            mock_instance = MagicMock()
            mock_bus.return_value = mock_instance
            tool(mock_ctx)
            mock_instance.emit_info.assert_called_once_with(
                "✅ Plan approved — entering auto-edit mode"
            )


class TestRegisterOpenPlanInEditor:
    def test_registers_tool(self):
        agent = MockAgent()
        register_open_plan_in_editor(agent)
        assert "open_plan_in_editor" in agent.tools

    def test_no_plans_directory(self):
        agent = MockAgent()
        register_open_plan_in_editor(agent)
        tool = agent.tools["open_plan_in_editor"]
        mock_ctx = MagicMock()
        with patch("code_muse.plugins.plan_mode.plan_mode_tools.Path") as mock_path_cls:
            mock_path = MagicMock()
            mock_path.exists.return_value = False
            mock_path_cls.return_value = mock_path
            result = tool(mock_ctx)
            assert "Error" in result
            assert "plans directory not found" in result

    def test_no_plan_files(self, tmp_path):
        plans_dir = tmp_path / "plans"
        plans_dir.mkdir()
        agent = MockAgent()
        register_open_plan_in_editor(agent)
        tool = agent.tools["open_plan_in_editor"]
        mock_ctx = MagicMock()
        with patch(
            "code_muse.plugins.plan_mode.plan_mode_tools.Path",
            return_value=plans_dir,
        ):
            result = tool(mock_ctx)
        assert "Error" in result
        assert "no plan files found" in result
