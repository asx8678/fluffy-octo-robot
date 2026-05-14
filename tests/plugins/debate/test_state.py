"""Tests for DebateState — budget, loop detection, agent-run lifecycle, history."""

import pytest

from code_muse.plugins.debate.schemas import VerdictKind
from code_muse.plugins.debate.state import DebateState


@pytest.fixture(autouse=True)
def _reset_state():
    """Ensure clean state before and after every test."""
    DebateState.reset()
    yield
    DebateState.reset()


# ---------------------------------------------------------------------------
# Budget
# ---------------------------------------------------------------------------


class TestBudget:
    def test_initial_state(self):
        assert DebateState.review_count() == 0
        assert DebateState.remaining_budget() == 20
        assert not DebateState.is_budget_exhausted()

    def test_review_increments_count(self):
        DebateState.record_review(1, VerdictKind.APPROVE)
        assert DebateState.review_count() == 1
        assert DebateState.remaining_budget() == 19

    def test_budget_exhausted(self):
        for i in range(20):
            DebateState.record_review(i + 1, VerdictKind.APPROVE)
        assert DebateState.is_budget_exhausted()
        assert DebateState.remaining_budget() == 0

    def test_budget_not_exhausted_below_limit(self):
        for i in range(19):
            DebateState.record_review(i + 1, VerdictKind.APPROVE)
        assert not DebateState.is_budget_exhausted()
        assert DebateState.remaining_budget() == 1


# ---------------------------------------------------------------------------
# Loop detection
# ---------------------------------------------------------------------------


class TestLoopDetection:
    def test_no_loop_initially(self):
        assert not DebateState.is_loop_detected()
        assert DebateState.consecutive_revisions() == 0

    def test_approve_resets_revisions(self):
        DebateState.record_review(1, VerdictKind.REVISE)
        DebateState.record_review(1, VerdictKind.REVISE)
        assert DebateState.consecutive_revisions() == 2
        DebateState.record_review(1, VerdictKind.APPROVE)
        assert DebateState.consecutive_revisions() == 0
        assert not DebateState.is_loop_detected()

    def test_reject_resets_revisions(self):
        DebateState.record_review(1, VerdictKind.REVISE)
        DebateState.record_review(1, VerdictKind.REVISE)
        DebateState.record_review(1, VerdictKind.REJECT)
        assert DebateState.consecutive_revisions() == 0

    def test_loop_detected_at_threshold(self):
        DebateState.record_review(1, VerdictKind.REVISE)
        DebateState.record_review(1, VerdictKind.REVISE)
        DebateState.record_review(1, VerdictKind.REVISE)
        assert DebateState.is_loop_detected()
        assert DebateState.consecutive_revisions() == 3

    def test_below_threshold_no_loop(self):
        DebateState.record_review(1, VerdictKind.REVISE)
        DebateState.record_review(1, VerdictKind.REVISE)
        assert not DebateState.is_loop_detected()

    def test_checkpoint_tracking(self):
        DebateState.record_review(5, VerdictKind.APPROVE)
        assert DebateState.current_checkpoint() == 5


# ---------------------------------------------------------------------------
# Agent-run lifecycle
# ---------------------------------------------------------------------------


class TestAgentRunLifecycle:
    def test_initially_inactive(self):
        assert not DebateState.is_active()
        assert DebateState.agent_name() is None

    def test_set_active(self):
        DebateState.set_active(True, "muse")
        assert DebateState.is_active()
        assert DebateState.agent_name() == "muse"

    def test_set_inactive_matching_name(self):
        DebateState.set_active(True, "muse")
        DebateState.set_active(False, "muse")
        assert not DebateState.is_active()
        assert DebateState.agent_name() is None

    def test_set_inactive_non_matching_name(self):
        DebateState.set_active(True, "muse")
        DebateState.set_active(False, "other-agent")
        assert DebateState.is_active()
        assert DebateState.agent_name() == "muse"

    def test_force_clear_with_none_name(self):
        DebateState.set_active(True, "muse")
        DebateState.set_active(False, None)
        assert not DebateState.is_active()


# ---------------------------------------------------------------------------
# Review history
# ---------------------------------------------------------------------------


class TestReviewHistory:
    def test_initially_empty(self):
        assert DebateState.review_history() == []

    def test_record_review_appends_history(self):
        DebateState.record_review(1, VerdictKind.APPROVE, "Looks good", 150.0)
        history = DebateState.review_history()
        assert len(history) == 1
        assert history[0]["checkpoint"] == 1
        assert history[0]["verdict"] == "approve"
        assert history[0]["summary"] == "Looks good"
        assert history[0]["latency_ms"] == 150.0

    def test_multiple_reviews_build_history(self):
        DebateState.record_review(1, VerdictKind.APPROVE, "OK", 100.0)
        DebateState.record_review(2, VerdictKind.REVISE, "Fix X", 200.0)
        DebateState.record_review(2, VerdictKind.APPROVE, "Fixed", 180.0)
        history = DebateState.review_history()
        assert len(history) == 3
        assert history[1]["verdict"] == "revise"
        assert history[2]["checkpoint"] == 2

    def test_history_returns_copy(self):
        DebateState.record_review(1, VerdictKind.APPROVE, "OK", 100.0)
        h1 = DebateState.review_history()
        h1.append({"fake": True})
        assert len(DebateState.review_history()) == 1

    def test_reset_clears_history(self):
        DebateState.record_review(1, VerdictKind.APPROVE, "OK", 50.0)
        DebateState.reset()
        assert DebateState.review_history() == []

    def test_default_summary_and_latency(self):
        DebateState.record_review(3, VerdictKind.REJECT)
        history = DebateState.review_history()
        assert history[0]["summary"] == ""
        assert history[0]["latency_ms"] == 0.0


# ---------------------------------------------------------------------------
# Reset
# ---------------------------------------------------------------------------


class TestReset:
    def test_reset_clears_everything(self):
        DebateState.record_review(1, VerdictKind.REVISE)
        DebateState.record_review(1, VerdictKind.REVISE)
        DebateState.record_review(1, VerdictKind.REVISE)
        DebateState.set_active(True, "muse")
        DebateState.reset()
        assert DebateState.review_count() == 0
        assert DebateState.consecutive_revisions() == 0
        assert not DebateState.is_active()
        assert DebateState.agent_name() is None
        assert DebateState.current_checkpoint() == 0
        assert DebateState.review_history() == []
