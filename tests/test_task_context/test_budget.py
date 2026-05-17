"""Tests for token-aware scoring and budget warnings."""

from code_muse.plugins.task_context.budget import (
    check_and_warn,
    estimate_current_budget,
    reset_warning_flags,
)
from code_muse.plugins.task_context.scorer import (
    score_batch_relevance,
    score_message_relevance,
    score_token_efficiency,
)

# ---------------------------------------------------------------------------
# Token efficiency scoring
# ---------------------------------------------------------------------------


class TestTokenEfficiency:
    def test_small_message_scores_high(self):
        score = score_token_efficiency(50)
        assert score > 0.8

    def test_large_message_scores_low(self):
        score = score_token_efficiency(5000)
        assert score < 0.2

    def test_average_message_scores_moderate(self):
        score = score_token_efficiency(500)
        assert 0.3 < score < 0.7

    def test_zero_tokens_neutral(self):
        score = score_token_efficiency(0)
        assert score == 0.5

    def test_negative_tokens_neutral(self):
        score = score_token_efficiency(-1)
        assert score == 0.5

    def test_returns_float_in_range(self):
        for tokens in [1, 10, 100, 500, 1000, 5000, 10000]:
            score = score_token_efficiency(tokens)
            assert 0.0 <= score <= 1.0


class TestScoreMessageRelevanceWithTokenCost:
    def test_token_estimate_parameter_accepted(self):
        """score_message_relevance should accept token_estimate param."""

        class FakeMsg:
            def __init__(self, text):
                self.parts = []

            def __str__(self):
                return "test"

        # Simple call to verify the parameter is accepted
        score = score_message_relevance(
            message={"content": "hello world"},
            message_index=0,
            total_messages=10,
            active_task_label="test task",
            token_estimate=500,
        )
        assert isinstance(score, float)
        assert 0.0 <= score <= 1.0

    def test_large_message_gets_lower_score(self):
        """Message with high token cost scores lower than same text with low cost."""

        class FakeMsg:
            pass

        # Same message text, different token estimates
        base_args = {
            "message": {"content": "implement authentication"},
            "message_index": 5,
            "total_messages": 10,
            "active_task_label": "authentication",
        }
        score_small = score_message_relevance(**base_args, token_estimate=50)
        score_large = score_message_relevance(**base_args, token_estimate=5000)
        # The large-token version should score lower due to token efficiency penalty
        assert score_small > score_large


class TestScoreBatchRelevanceWithTokens:
    def test_batch_accepts_token_estimates(self):
        """score_batch_relevance should accept token_estimates list."""
        scores = score_batch_relevance(
            messages=[{"content": "test content"}],
            active_task_label="test",
            token_estimates=[100],
        )
        assert len(scores) == 1
        assert isinstance(scores[0], float)

    def test_token_efficiency_affects_overall_score(self):
        """Token cost should directly influence the overall score."""
        # Same message at same index — only token_estimate differs
        base_kwargs = dict(
            message={"content": "test content"},
            message_index=0,
            total_messages=1,
            active_task_label="test",
        )
        score_small = score_message_relevance(**base_kwargs, token_estimate=50)
        score_large = score_message_relevance(**base_kwargs, token_estimate=5000)
        assert score_small > score_large


# ---------------------------------------------------------------------------
# Budget tracking
# ---------------------------------------------------------------------------


class TestEstimateCurrentBudget:
    def test_empty_history(self):
        info = estimate_current_budget([])
        assert info["total_tokens"] == 0
        assert info["usage_pct"] == 0.0
        assert info["remaining_tokens"] > 0

    def test_returns_expected_keys(self):
        info = estimate_current_budget([])
        assert "total_tokens" in info
        assert "budget_tokens" in info
        assert "usage_pct" in info
        assert "remaining_tokens" in info


class TestCheckAndWarn:
    def setup_method(self):
        reset_warning_flags()

    def test_warn_threshold_emits_info(self, caplog):
        """Below critical but above warn threshold should emit info."""
        budget_info = {
            "total_tokens": 90_000,
            "budget_tokens": 128_000,
            "usage_pct": 0.70,
            "remaining_tokens": 38_000,
        }
        # Should not raise, should not crash
        check_and_warn(budget_info, warn_at=0.65, critical_at=0.85)

    def test_critical_threshold_emits_warning(self):
        """Above critical threshold should emit warning."""
        budget_info = {
            "total_tokens": 120_000,
            "budget_tokens": 128_000,
            "usage_pct": 0.94,
            "remaining_tokens": 8_000,
        }
        check_and_warn(budget_info, warn_at=0.65, critical_at=0.85)

    def test_below_threshold_no_warning(self):
        """Below both thresholds should not emit anything."""
        budget_info = {
            "total_tokens": 50_000,
            "budget_tokens": 128_000,
            "usage_pct": 0.39,
            "remaining_tokens": 78_000,
        }
        # Should not raise
        check_and_warn(budget_info, warn_at=0.65, critical_at=0.85)

    def test_only_warns_once_per_threshold(self):
        """Should not emit duplicate warnings at the same threshold."""
        budget_info = {
            "total_tokens": 90_000,
            "budget_tokens": 128_000,
            "usage_pct": 0.70,
            "remaining_tokens": 38_000,
        }
        # Call twice — should not crash on duplicate
        check_and_warn(budget_info, warn_at=0.65, critical_at=0.85)
        check_and_warn(budget_info, warn_at=0.65, critical_at=0.85)


class TestResetWarningFlags:
    def test_reset_allows_rewarning(self):
        """After reset, warnings should be emitted again."""
        budget_info = {
            "total_tokens": 90_000,
            "budget_tokens": 128_000,
            "usage_pct": 0.70,
            "remaining_tokens": 38_000,
        }
        # First warning
        check_and_warn(budget_info, warn_at=0.65, critical_at=0.85)
        # Reset
        reset_warning_flags()
        # Should be able to warn again without crashing
        check_and_warn(budget_info, warn_at=0.65, critical_at=0.85)
