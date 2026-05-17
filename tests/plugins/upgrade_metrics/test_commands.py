"""Tests for /metrics slash commands — compression, context, quality,
status, off, on, reset."""

import pytest

import code_muse.plugins.upgrade_metrics.register_callbacks as _mod
from code_muse.plugins.upgrade_metrics.register_callbacks import (
    _event_buffer,
    _on_custom_command,
    _on_custom_command_help,
    _reset_events,
    _reset_ledger,
    emit_metric,
)


@pytest.fixture(autouse=True)
def _reset():
    """Ensure clean state before and after every test."""
    _reset_ledger()
    _reset_events()
    _mod._enabled = True
    yield
    _reset_ledger()
    _reset_events()
    _mod._enabled = True


# ---------------------------------------------------------------------------
# /metrics compression
# ---------------------------------------------------------------------------


class TestMetricsCompressionCommand:
    def test_returns_true(self):
        result = _on_custom_command("/metrics compression", "metrics")
        assert result is True

    def test_shows_savings(self):
        emit_metric(
            "compression_applied",
            {
                "original_tokens": 5000,
                "compressed_tokens": 3000,
                "strategy": "semantic",
            },
        )
        # Should not raise
        _on_custom_command("/metrics compression", "metrics")

    def test_empty_compression(self):
        # No events — should still return True and show zeros
        result = _on_custom_command("/metrics compression", "metrics")
        assert result is True


# ---------------------------------------------------------------------------
# /metrics context
# ---------------------------------------------------------------------------


class TestMetricsContextCommand:
    def test_returns_true(self):
        result = _on_custom_command("/metrics context", "metrics")
        assert result is True

    def test_shows_pruning_stats(self):
        emit_metric("context_pruned", {"messages_pruned": 5, "tokens_saved": 1200})
        _on_custom_command("/metrics context", "metrics")


# ---------------------------------------------------------------------------
# /metrics quality
# ---------------------------------------------------------------------------


class TestMetricsQualityCommand:
    def test_returns_true(self):
        result = _on_custom_command("/metrics quality", "metrics")
        assert result is True

    def test_shows_verdict_distribution(self):
        emit_metric("review_verdict", {"verdict": "approve"})
        emit_metric("review_verdict", {"verdict": "revise"})
        emit_metric("review_verdict", {"verdict": "approve", "overridden": True})
        _on_custom_command("/metrics quality", "metrics")


# ---------------------------------------------------------------------------
# /metrics status
# ---------------------------------------------------------------------------


class TestMetricsStatusCommand:
    def test_returns_true(self):
        result = _on_custom_command("/metrics status", "metrics")
        assert result is True

    def test_shows_enabled_state(self):
        _mod._enabled = True
        _on_custom_command("/metrics status", "metrics")

    def test_shows_disabled_state(self):
        _mod._enabled = False
        # Status should still work even when disabled (it's a read command)
        # The command handler itself checks name first, then sub.
        # When disabled, the handler still processes the command.
        # Verify it shows disabled:
        result = _on_custom_command("/metrics status", "metrics")
        assert result is True


# ---------------------------------------------------------------------------
# /metrics off
# ---------------------------------------------------------------------------


class TestMetricsOffDisables:
    def test_off_disables_plugin(self):
        result = _on_custom_command("/metrics off", "metrics")
        assert result is True
        assert _mod._enabled is False

    def test_emit_metric_noop_after_off(self):
        _on_custom_command("/metrics off", "metrics")
        emit_metric("compression_applied", {"original_tokens": 5000})
        assert len(_event_buffer) == 0


# ---------------------------------------------------------------------------
# /metrics on
# ---------------------------------------------------------------------------


class TestMetricsOnReenables:
    def test_on_reenables_plugin(self):
        _mod._enabled = False
        result = _on_custom_command("/metrics on", "metrics")
        assert result is True
        assert _mod._enabled is True

    def test_emit_metric_works_after_on(self):
        _on_custom_command("/metrics off", "metrics")
        _on_custom_command("/metrics on", "metrics")
        emit_metric("compression_applied", {"original_tokens": 5000})
        assert len(_event_buffer) == 1


# ---------------------------------------------------------------------------
# /metrics reset
# ---------------------------------------------------------------------------


class TestMetricsReset:
    def test_reset_clears_in_memory_state(self):
        emit_metric(
            "compression_applied",
            {"original_tokens": 5000, "compressed_tokens": 3000},
        )
        from code_muse.plugins.upgrade_metrics.register_callbacks import record_tokens

        record_tokens("input", 1000)
        result = _on_custom_command("/metrics reset", "metrics")
        assert result is True
        assert len(_event_buffer) == 0

        from code_muse.plugins.upgrade_metrics.register_callbacks import get_ledger

        ledger = get_ledger()
        for stage in (
            "input",
            "after_compression",
            "after_compaction",
            "after_review",
            "current",
        ):
            assert ledger[stage] == 0


# ---------------------------------------------------------------------------
# /upgrade-metrics off alias
# ---------------------------------------------------------------------------


class TestUpgradeMetricsOffAlias:
    def test_upgrade_metrics_off_works(self):
        result = _on_custom_command("/upgrade-metrics off", "upgrade-metrics")
        assert result is True
        assert _mod._enabled is False

    def test_upgrade_metrics_on_works(self):
        _mod._enabled = False
        result = _on_custom_command("/upgrade-metrics on", "upgrade-metrics")
        assert result is True
        assert _mod._enabled is True


# ---------------------------------------------------------------------------
# Unknown command passthrough
# ---------------------------------------------------------------------------


class TestUnknownCommandPassthrough:
    def test_non_metrics_command_returns_none(self):
        result = _on_custom_command("/other", "other")
        assert result is None

    def test_unknown_name_returns_none(self):
        result = _on_custom_command("/something", "something")
        assert result is None


# ---------------------------------------------------------------------------
# custom_command_help
# ---------------------------------------------------------------------------


class TestHelpEntries:
    def test_returns_list_of_tuples(self):
        entries = _on_custom_command_help()
        assert isinstance(entries, list)
        assert all(isinstance(e, tuple) and len(e) == 2 for e in entries)

    def test_includes_expected_commands(self):
        entries = _on_custom_command_help()
        commands = {cmd for cmd, _ in entries}
        assert "metrics compression" in commands
        assert "metrics context" in commands
        assert "metrics quality" in commands
        assert "metrics status" in commands
        assert "metrics off" in commands
        assert "metrics on" in commands
        assert "metrics reset" in commands
        assert "metrics help" in commands

    def test_includes_upgrade_metrics_aliases(self):
        entries = _on_custom_command_help()
        commands = {cmd for cmd, _ in entries}
        assert "upgrade-metrics off" in commands
        assert "upgrade-metrics on" in commands
