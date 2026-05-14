"""Tests for /debate slash commands — toggle, status, stats, metrics, history, reset."""

import pytest

from code_muse.plugins.debate.config import is_debate_enabled, set_debate_enabled

# Import the command handler directly (no CLI needed)
from code_muse.plugins.debate.register_callbacks import _on_custom_command
from code_muse.plugins.debate.schemas import VerdictKind
from code_muse.plugins.debate.state import DebateState
from code_muse.plugins.debate.telemetry import reset_telemetry


@pytest.fixture(autouse=True)
def _reset():
    DebateState.reset()
    reset_telemetry()
    set_debate_enabled(True)
    yield
    DebateState.reset()
    reset_telemetry()
    set_debate_enabled(True)


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------


class TestRouting:
    def test_non_debate_command_ignored(self):
        result = _on_custom_command("/other", "other")
        assert result is None

    def test_debate_no_sub_defaults_to_status(self):
        result = _on_custom_command("/debate", "debate")
        assert result is True

    def test_unknown_subcommand_shows_usage(self):
        result = _on_custom_command("/debate unknown", "debate")
        assert result is True


# ---------------------------------------------------------------------------
# Toggle commands
# ---------------------------------------------------------------------------


class TestToggleCommands:
    def test_on(self):
        set_debate_enabled(False)
        result = _on_custom_command("/debate on", "debate")
        assert result is True
        assert is_debate_enabled() is True

    def test_off(self):
        result = _on_custom_command("/debate off", "debate")
        assert result is True
        assert is_debate_enabled() is False

    def test_toggle_on_to_off(self):
        assert is_debate_enabled() is True
        result = _on_custom_command("/debate toggle", "debate")
        assert result is True
        assert is_debate_enabled() is False

    def test_toggle_off_to_on(self):
        set_debate_enabled(False)
        result = _on_custom_command("/debate toggle", "debate")
        assert result is True
        assert is_debate_enabled() is True


# ---------------------------------------------------------------------------
# Status command
# ---------------------------------------------------------------------------


class TestStatusCommand:
    def test_returns_true(self):
        result = _on_custom_command("/debate status", "debate")
        assert result is True

    def test_shows_enabled(self):
        # Should not raise
        _on_custom_command("/debate status", "debate")

    def test_shows_disabled(self):
        set_debate_enabled(False)
        _on_custom_command("/debate status", "debate")


# ---------------------------------------------------------------------------
# Stats command
# ---------------------------------------------------------------------------


class TestStatsCommand:
    def test_returns_true(self):
        result = _on_custom_command("/debate stats", "debate")
        assert result is True

    def test_with_reviews(self):
        DebateState.record_review(1, VerdictKind.APPROVE, "OK", 100.0)
        result = _on_custom_command("/debate stats", "debate")
        assert result is True


# ---------------------------------------------------------------------------
# Metrics command
# ---------------------------------------------------------------------------


class TestMetricsCommand:
    def test_returns_true(self):
        result = _on_custom_command("/debate metrics", "debate")
        assert result is True

    def test_with_data(self):
        DebateState.record_review(1, VerdictKind.APPROVE, "OK", 100.0)
        DebateState.record_review(2, VerdictKind.REVISE, "Fix", 200.0)
        result = _on_custom_command("/debate metrics", "debate")
        assert result is True


# ---------------------------------------------------------------------------
# History command
# ---------------------------------------------------------------------------


class TestHistoryCommand:
    def test_returns_true(self):
        result = _on_custom_command("/debate history", "debate")
        assert result is True

    def test_with_history(self):
        DebateState.record_review(1, VerdictKind.APPROVE, "Looks good", 150.0)
        DebateState.record_review(2, VerdictKind.REVISE, "Fix X", 200.0)
        result = _on_custom_command("/debate history", "debate")
        assert result is True


# ---------------------------------------------------------------------------
# Reset command
# ---------------------------------------------------------------------------


class TestResetCommand:
    def test_returns_true(self):
        result = _on_custom_command("/debate reset", "debate")
        assert result is True

    def test_clears_state(self):
        DebateState.record_review(1, VerdictKind.APPROVE, "OK", 100.0)
        _on_custom_command("/debate reset", "debate")
        assert DebateState.review_count() == 0
        assert DebateState.review_history() == []

    def test_clears_telemetry(self):
        from code_muse.plugins.debate.telemetry import get_session_stats

        DebateState.record_review(1, VerdictKind.APPROVE, "OK", 100.0)
        _on_custom_command("/debate reset", "debate")
        stats = get_session_stats()
        assert stats["total_reviews"] == 0
