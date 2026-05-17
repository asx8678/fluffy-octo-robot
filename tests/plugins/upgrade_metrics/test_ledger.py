"""Tests for the Upgrade Metrics token ledger."""

import pytest

from code_muse.plugins.upgrade_metrics.register_callbacks import (
    _LEDGER_STAGES,
    _reset_ledger,
    get_ledger,
    record_tokens,
)


@pytest.fixture(autouse=True)
def _reset():
    """Ensure clean ledger state before and after every test."""
    _reset_ledger()
    yield
    _reset_ledger()


# ---------------------------------------------------------------------------
# Initial state
# ---------------------------------------------------------------------------


class TestInitialLedger:
    def test_all_stages_start_at_zero(self):
        ledger = get_ledger()
        for stage in _LEDGER_STAGES:
            assert ledger[stage] == 0, f"Stage {stage!r} should start at 0"

    def test_ledger_has_all_stages(self):
        ledger = get_ledger()
        expected = {
            "input",
            "after_compression",
            "after_compaction",
            "after_review",
            "current",
        }
        assert set(ledger.keys()) == expected


# ---------------------------------------------------------------------------
# record_tokens
# ---------------------------------------------------------------------------


class TestRecordTokens:
    def test_record_at_each_stage(self):
        record_tokens("input", 1000)
        record_tokens("after_compression", 800)
        record_tokens("after_compaction", 600)
        record_tokens("after_review", 550)
        record_tokens("current", 500)

        ledger = get_ledger()
        assert ledger["input"] == 1000
        assert ledger["after_compression"] == 800
        assert ledger["after_compaction"] == 600
        assert ledger["after_review"] == 550
        assert ledger["current"] == 500

    def test_record_is_cumulative(self):
        """record_tokens ADDS to the existing value, not replaces."""
        record_tokens("input", 1000)
        record_tokens("input", 500)
        assert get_ledger()["input"] == 1500

    def test_record_unknown_stage_ignored(self):
        """record_tokens logs a warning and ignores unknown stages."""
        record_tokens("nonexistent", 100)
        # Should not raise, should not add to ledger
        assert "nonexistent" not in get_ledger()

    def test_record_zero_tokens(self):
        record_tokens("input", 0)
        assert get_ledger()["input"] == 0


# ---------------------------------------------------------------------------
# get_ledger snapshot
# ---------------------------------------------------------------------------


class TestLedgerSnapshot:
    def test_returns_correct_dict(self):
        record_tokens("input", 2000)
        snapshot = get_ledger()
        assert snapshot == {
            "input": 2000,
            "after_compression": 0,
            "after_compaction": 0,
            "after_review": 0,
            "current": 0,
        }

    def test_snapshot_is_copy(self):
        """Mutating the returned dict does not affect the internal ledger."""
        record_tokens("input", 1000)
        snapshot = get_ledger()
        snapshot["input"] = 9999
        assert get_ledger()["input"] == 1000


# ---------------------------------------------------------------------------
# Reset
# ---------------------------------------------------------------------------


class TestResetClearsLedger:
    def test_reset_zeros_everything(self):
        record_tokens("input", 5000)
        record_tokens("after_compression", 4000)
        _reset_ledger()
        ledger = get_ledger()
        for stage in _LEDGER_STAGES:
            assert ledger[stage] == 0, f"Stage {stage!r} should be 0 after reset"

    def test_record_after_reset(self):
        record_tokens("input", 1000)
        _reset_ledger()
        record_tokens("input", 500)
        assert get_ledger()["input"] == 500
