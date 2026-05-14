"""Tests for debate plugin hooks — pre_tool_call gating, load_prompt, agent-run."""

import asyncio

import pytest

from code_muse.plugins.debate.register_callbacks import (
    _on_agent_run_end,
    _on_agent_run_start,
    _on_load_prompt,
    _on_pre_tool_call,
)
from code_muse.plugins.debate.schemas import VerdictKind
from code_muse.plugins.debate.state import DebateState


@pytest.fixture(autouse=True)
def _reset_state():
    """Ensure clean state before and after every test."""
    DebateState.reset()
    yield
    DebateState.reset()


# ---------------------------------------------------------------------------
# pre_tool_call gating
# ---------------------------------------------------------------------------


class TestPreToolCallGating:
    """Verify pre_tool_call returns {"blocked": True} when limits are hit
    and None otherwise.  It must NEVER return results — only gate."""

    def test_non_debate_tool_passes_through(self):
        result = asyncio.run(_on_pre_tool_call("create_file", {}))
        assert result is None

    def test_request_review_passes_when_budget_available(self):
        result = asyncio.run(_on_pre_tool_call("request_review", {}))
        assert result is None

    def test_request_review_blocked_when_budget_exhausted(self):
        for i in range(20):
            DebateState.record_review(i + 1, VerdictKind.APPROVE)
        result = asyncio.run(_on_pre_tool_call("request_review", {}))
        assert result == {"blocked": True}

    def test_request_review_blocked_when_loop_detected(self):
        DebateState.record_review(1, VerdictKind.REVISE)
        DebateState.record_review(1, VerdictKind.REVISE)
        DebateState.record_review(1, VerdictKind.REVISE)
        result = asyncio.run(_on_pre_tool_call("request_review", {}))
        assert result == {"blocked": True}

    def test_below_loop_threshold_passes(self):
        DebateState.record_review(1, VerdictKind.REVISE)
        DebateState.record_review(1, VerdictKind.REVISE)
        result = asyncio.run(_on_pre_tool_call("request_review", {}))
        assert result is None

    def test_approve_resets_loop_counter_and_passes(self):
        DebateState.record_review(1, VerdictKind.REVISE)
        DebateState.record_review(1, VerdictKind.REVISE)
        # Approve resets consecutive revisions
        DebateState.record_review(2, VerdictKind.APPROVE)
        result = asyncio.run(_on_pre_tool_call("request_review", {}))
        assert result is None

    def test_other_tools_never_blocked_even_with_exhausted_budget(self):
        for i in range(20):
            DebateState.record_review(i + 1, VerdictKind.APPROVE)
        result = asyncio.run(_on_pre_tool_call("replace_in_file", {}))
        assert result is None


# ---------------------------------------------------------------------------
# load_prompt hook
# ---------------------------------------------------------------------------


class TestLoadPrompt:
    """Verify the planner addendum is injected when debate is enabled."""

    def test_returns_addendum_when_enabled(self):
        result = _on_load_prompt()
        # Debate is enabled by default
        assert result is not None
        assert "request_review" in result
        assert "checkpoint" in result

    def test_addendum_contains_verdict_instructions(self):
        result = _on_load_prompt()
        assert "approve" in result.lower()
        assert "revise" in result.lower()
        assert "reject" in result.lower()

    def test_returns_none_when_disabled(self, monkeypatch):
        # Patch the function where it's looked up — in register_callbacks module
        import code_muse.plugins.debate.register_callbacks as rc_mod

        original = rc_mod.is_debate_enabled
        monkeypatch.setattr(rc_mod, "is_debate_enabled", lambda: False)
        result = _on_load_prompt()
        assert result is None
        monkeypatch.setattr(rc_mod, "is_debate_enabled", original)


# ---------------------------------------------------------------------------
# agent_run_start / agent_run_end hooks
# ---------------------------------------------------------------------------


class TestAgentRunHooks:
    """Verify agent-run lifecycle tracking via hooks."""

    def test_agent_run_start_sets_active(self):
        asyncio.run(_on_agent_run_start("muse", "claude-3.5-sonnet", "s1"))
        assert DebateState.is_active()
        assert DebateState.agent_name() == "muse"

    def test_agent_run_end_clears_active(self):
        asyncio.run(_on_agent_run_start("muse", "claude-3.5-sonnet", "s1"))
        asyncio.run(_on_agent_run_end("muse", "claude-3.5-sonnet", "s1", success=True))
        assert not DebateState.is_active()

    def test_mismatched_agent_run_end_does_not_clear(self):
        asyncio.run(_on_agent_run_start("muse", "claude-3.5-sonnet", "s1"))
        asyncio.run(_on_agent_run_end("other", "claude-3.5-sonnet", "s2", success=True))
        assert DebateState.is_active()
        assert DebateState.agent_name() == "muse"

    def test_disabled_hooks_are_noop(self, monkeypatch):
        import code_muse.plugins.debate.register_callbacks as rc_mod

        monkeypatch.setattr(rc_mod, "is_debate_enabled", lambda: False)
        asyncio.run(_on_agent_run_start("muse", "claude-3.5-sonnet"))
        assert not DebateState.is_active()
