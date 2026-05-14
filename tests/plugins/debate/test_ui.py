"""Tests for the Debate Mode UI rendering module."""

from code_muse.plugins.debate.schemas import VerdictKind
from code_muse.plugins.debate.ui import (
    render_progress_bar,
    render_review_history,
    render_status_panel,
    render_verdict_summary,
    show_reviewing,
    show_verdict,
)

# ---------------------------------------------------------------------------
# show_reviewing
# ---------------------------------------------------------------------------


class TestShowReviewing:
    def test_basic(self):
        result = show_reviewing(3)
        assert result == "🔍 Debating checkpoint 3"

    def test_with_preview(self):
        result = show_reviewing(1, "Refactor the auth module")
        assert "🔍 Debating checkpoint 1" in result
        assert "Refactor the auth module" in result

    def test_preview_truncated(self):
        long_text = "x" * 200
        result = show_reviewing(2, long_text)
        assert len(result) < 200  # Should be truncated

    def test_preview_newlines_stripped(self):
        result = show_reviewing(1, "line1\nline2\nline3")
        assert "\n" not in result.split("— ", 1)[-1].rstrip("…")


# ---------------------------------------------------------------------------
# show_verdict
# ---------------------------------------------------------------------------


class TestShowVerdict:
    def test_approve(self):
        result = show_verdict(VerdictKind.APPROVE, "Looks good")
        assert "✅" in result
        assert "APPROVE" in result
        assert "Looks good" in result

    def test_revise(self):
        result = show_verdict(VerdictKind.REVISE, "Fix errors")
        assert "🔄" in result
        assert "REVISE" in result

    def test_reject(self):
        result = show_verdict(VerdictKind.REJECT, "Dangerous")
        assert "❌" in result
        assert "REJECT" in result

    def test_with_issues(self):
        issues = [
            {
                "severity": "critical",
                "message": "SQL injection",
                "suggestion": "Use params",
            },
            {"severity": "warning", "message": "Missing tests"},
        ]
        result = show_verdict(
            VerdictKind.REVISE, "Needs work", issues=issues, confidence=0.6
        )
        assert "SQL injection" in result
        assert "Use params" in result
        assert "Missing tests" in result
        assert "🔴" in result
        assert "🟡" in result

    def test_confidence_bar(self):
        result = show_verdict(VerdictKind.APPROVE, "OK", confidence=0.8)
        assert "80%" in result
        assert "█" in result

    def test_budget_displayed(self):
        result = show_verdict(
            VerdictKind.APPROVE, "OK", review_count=5, remaining_budget=15
        )
        assert "15 remaining" in result
        assert "5 reviews used" in result

    def test_issues_capped_at_five(self):
        issues = [{"severity": "info", "message": f"Issue {i}"} for i in range(8)]
        result = show_verdict(VerdictKind.REVISE, "Many issues", issues=issues)
        # 8 issues - 5 cap = 3 more
        assert "3 more" in result

    def test_no_issues(self):
        result = show_verdict(VerdictKind.APPROVE, "Clean", issues=None)
        assert "Issues:" not in result


# ---------------------------------------------------------------------------
# render_verdict_summary
# ---------------------------------------------------------------------------


class TestRenderVerdictSummary:
    def test_approve(self):
        result = render_verdict_summary(VerdictKind.APPROVE, "All good", 3, 17)
        assert "✅" in result
        assert "#3" in result
        assert "APPROVE" in result
        assert "17 remaining" in result

    def test_revise(self):
        result = render_verdict_summary(VerdictKind.REVISE, "Fix X", 5, 15)
        assert "🔄" in result
        assert "#5" in result


# ---------------------------------------------------------------------------
# render_progress_bar
# ---------------------------------------------------------------------------


class TestProgressBar:
    def test_zero_used(self):
        result = render_progress_bar(0, 20)
        assert "0/20" in result
        assert "0%" in result
        assert "░" in result

    def test_half_used(self):
        result = render_progress_bar(10, 20)
        assert "10/20" in result
        assert "50%" in result

    def test_full(self):
        result = render_progress_bar(20, 20)
        assert "20/20" in result
        assert "100%" in result
        assert "█" in result

    def test_zero_total(self):
        result = render_progress_bar(0, 0)
        assert "0/0" in result

    def test_custom_width(self):
        result = render_progress_bar(5, 10, width=10)
        assert "5/10" in result


# ---------------------------------------------------------------------------
# render_review_history
# ---------------------------------------------------------------------------


class TestReviewHistory:
    def test_empty(self):
        result = render_review_history([])
        assert "No reviews" in result

    def test_single_entry(self):
        history = [
            {
                "checkpoint": 1,
                "verdict": "approve",
                "latency_ms": 150.0,
                "summary": "OK",
            }
        ]
        result = render_review_history(history)
        assert "✅" in result
        assert "approve" in result
        assert "150ms" in result

    def test_multiple_entries(self):
        history = [
            {
                "checkpoint": 1,
                "verdict": "approve",
                "latency_ms": 100.0,
                "summary": "OK",
            },
            {
                "checkpoint": 2,
                "verdict": "revise",
                "latency_ms": 200.0,
                "summary": "Fix X",
            },
            {
                "checkpoint": 2,
                "verdict": "approve",
                "latency_ms": 150.0,
                "summary": "Fixed",
            },
        ]
        result = render_review_history(history)
        assert "✅" in result
        assert "🔄" in result

    def test_long_summary_truncated(self):
        history = [
            {
                "checkpoint": 1,
                "verdict": "approve",
                "latency_ms": 50.0,
                "summary": "x" * 100,
            }
        ]
        result = render_review_history(history)
        lines = result.split("\n")
        data_line = [ln for ln in lines if "✅" in ln][0]
        assert len(data_line) < 150  # Summary should be truncated


# ---------------------------------------------------------------------------
# render_status_panel
# ---------------------------------------------------------------------------


class TestStatusPanel:
    def test_enabled(self):
        result = render_status_panel(
            enabled=True,
            active=False,
            agent_name=None,
            review_count=3,
            remaining_budget=17,
            max_reviews=20,
            consecutive_revisions=0,
            max_loops=3,
            avg_latency_ms=120.0,
        )
        assert "ON" in result
        assert "idle" in result
        assert "3" in result
        assert "0/3" in result  # loop risk

    def test_disabled(self):
        result = render_status_panel(
            enabled=False,
            active=False,
            agent_name=None,
            review_count=0,
            remaining_budget=20,
            max_reviews=20,
            consecutive_revisions=0,
            max_loops=3,
            avg_latency_ms=0.0,
        )
        assert "OFF" in result

    def test_active_agent(self):
        result = render_status_panel(
            enabled=True,
            active=True,
            agent_name="muse",
            review_count=1,
            remaining_budget=19,
            max_reviews=20,
            consecutive_revisions=1,
            max_loops=3,
            avg_latency_ms=200.0,
        )
        assert "muse" in result
        assert "active" in result
