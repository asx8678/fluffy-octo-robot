"""Tests for the Debate Mode telemetry module."""

import time

import pytest

from code_muse.plugins.debate.schemas import VerdictKind
from code_muse.plugins.debate.telemetry import (
    get_latency_stats,
    get_session_stats,
    get_success_rate,
    get_verdict_breakdown,
    record_review_latency,
    reset_telemetry,
)


@pytest.fixture(autouse=True)
def _reset():
    """Ensure clean telemetry state before and after every test."""
    reset_telemetry()
    yield
    reset_telemetry()


# ---------------------------------------------------------------------------
# record_review_latency
# ---------------------------------------------------------------------------


class TestRecordLatency:
    def test_single_review(self):
        start = time.monotonic() - 0.1  # 100ms ago
        record_review_latency(start, VerdictKind.APPROVE)
        stats = get_session_stats()
        assert stats["total_reviews"] == 1

    def test_verdict_counts_updated(self):
        start = time.monotonic() - 0.05
        record_review_latency(start, VerdictKind.APPROVE)
        record_review_latency(start, VerdictKind.REVISE)
        record_review_latency(start, VerdictKind.APPROVE)
        breakdown = get_verdict_breakdown()
        assert breakdown["approve"] == 2
        assert breakdown["revise"] == 1
        assert breakdown["reject"] == 0

    def test_latency_tracked(self):
        start = time.monotonic() - 0.2
        record_review_latency(start, VerdictKind.APPROVE)
        latency = get_latency_stats()
        assert latency["avg_ms"] > 0
        assert latency["min_ms"] > 0
        assert latency["max_ms"] > 0
        assert latency["total_ms"] > 0


# ---------------------------------------------------------------------------
# get_session_stats
# ---------------------------------------------------------------------------


class TestSessionStats:
    def test_initial_state(self):
        stats = get_session_stats()
        assert stats["total_reviews"] == 0
        assert stats["success_rate"] == 0.0
        assert stats["avg_latency_ms"] == 0.0
        assert stats["min_latency_ms"] == 0.0
        assert stats["max_latency_ms"] == 0.0

    def test_after_reviews(self):
        start = time.monotonic() - 0.1
        record_review_latency(start, VerdictKind.APPROVE)
        stats = get_session_stats()
        assert stats["total_reviews"] == 1
        assert stats["success_rate"] == 1.0
        assert stats["avg_latency_ms"] > 0

    def test_verdict_counts_snapshot(self):
        start = time.monotonic() - 0.01
        record_review_latency(start, VerdictKind.APPROVE)
        record_review_latency(start, VerdictKind.REVISE)
        stats = get_session_stats()
        vc = stats["verdict_counts"]
        assert vc["approve"] == 1
        assert vc["revise"] == 1

    def test_reviews_per_minute(self):
        # Need at least 2 reviews with time gap for rate calc
        start = time.monotonic() - 0.05
        record_review_latency(start, VerdictKind.APPROVE)
        time.sleep(0.01)
        start = time.monotonic() - 0.05
        record_review_latency(start, VerdictKind.APPROVE)
        stats = get_session_stats()
        assert stats["reviews_per_minute"] > 0


# ---------------------------------------------------------------------------
# get_success_rate
# ---------------------------------------------------------------------------


class TestSuccessRate:
    def test_zero_reviews(self):
        assert get_success_rate() == 0.0

    def test_all_approve(self):
        start = time.monotonic() - 0.01
        record_review_latency(start, VerdictKind.APPROVE)
        record_review_latency(start, VerdictKind.APPROVE)
        assert get_success_rate() == 1.0

    def test_mixed(self):
        start = time.monotonic() - 0.01
        record_review_latency(start, VerdictKind.APPROVE)
        record_review_latency(start, VerdictKind.REVISE)
        record_review_latency(start, VerdictKind.REJECT)
        rate = get_success_rate()
        assert 0.0 < rate < 1.0
        assert rate == pytest.approx(1 / 3, abs=0.01)

    def test_no_approves(self):
        start = time.monotonic() - 0.01
        record_review_latency(start, VerdictKind.REVISE)
        assert get_success_rate() == 0.0


# ---------------------------------------------------------------------------
# get_verdict_breakdown
# ---------------------------------------------------------------------------


class TestVerdictBreakdown:
    def test_initial(self):
        bd = get_verdict_breakdown()
        assert bd == {"approve": 0, "revise": 0, "reject": 0}

    def test_after_reviews(self):
        start = time.monotonic() - 0.01
        record_review_latency(start, VerdictKind.APPROVE)
        record_review_latency(start, VerdictKind.REVISE)
        record_review_latency(start, VerdictKind.REVISE)
        record_review_latency(start, VerdictKind.REJECT)
        bd = get_verdict_breakdown()
        assert bd["approve"] == 1
        assert bd["revise"] == 2
        assert bd["reject"] == 1


# ---------------------------------------------------------------------------
# get_latency_stats
# ---------------------------------------------------------------------------


class TestLatencyStats:
    def test_initial(self):
        stats = get_latency_stats()
        assert stats["avg_ms"] == 0.0
        assert stats["min_ms"] == 0.0
        assert stats["max_ms"] == 0.0
        assert stats["total_ms"] == 0.0

    def test_min_max(self):
        # Short review
        start_short = time.monotonic() - 0.05
        record_review_latency(start_short, VerdictKind.APPROVE)
        # Long review
        start_long = time.monotonic() - 0.5
        record_review_latency(start_long, VerdictKind.REVISE)
        stats = get_latency_stats()
        assert stats["min_ms"] < stats["max_ms"]
        assert stats["total_ms"] > 0


# ---------------------------------------------------------------------------
# reset_telemetry
# ---------------------------------------------------------------------------


class TestResetTelemetry:
    def test_reset_clears_all(self):
        start = time.monotonic() - 0.1
        record_review_latency(start, VerdictKind.APPROVE)
        record_review_latency(start, VerdictKind.REVISE)
        reset_telemetry()
        stats = get_session_stats()
        assert stats["total_reviews"] == 0
        assert get_success_rate() == 0.0
        assert get_verdict_breakdown() == {"approve": 0, "revise": 0, "reject": 0}
