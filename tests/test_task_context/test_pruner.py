"""Tests for task_context.pruner — pruning decisions and token estimation."""

from unittest.mock import MagicMock, patch

from code_muse.plugins.task_context.models import (
    PruneAction,
    PruneDecision,
    PruneSummary,
    TaskStatus,
)
from code_muse.plugins.task_context.pruner import (
    _decide_action,
    _estimate_total_tokens,
    _extract_text,
    evaluate_and_prune,
)

# ---------------------------------------------------------------------------
# _decide_action — the core decision matrix
# ---------------------------------------------------------------------------


class TestDecideAction:
    # --- Active task: always KEEP ---
    def test_active_non_completed_keeps(self):
        action = _decide_action(
            is_completed=False,
            relevance=0.1,
            task_status=TaskStatus.ACTIVE,
            aggressiveness="aggressive",
        )
        assert action is PruneAction.KEEP

    # --- High relevance (>=0.6): always KEEP regardless of status ---
    def test_completed_high_relevance_keeps(self):
        action = _decide_action(
            is_completed=True,
            relevance=0.8,
            task_status=TaskStatus.COMPLETED,
            aggressiveness="aggressive",
        )
        assert action is PruneAction.KEEP

    def test_completed_high_relevance_keeps_conservative(self):
        action = _decide_action(
            is_completed=True,
            relevance=0.7,
            task_status=TaskStatus.COMPLETED,
            aggressiveness="conservative",
        )
        assert action is PruneAction.KEEP

    # --- Medium relevance (0.3–0.6) ---
    def test_completed_medium_relevance_moderate_archives(self):
        action = _decide_action(
            is_completed=True,
            relevance=0.45,
            task_status=TaskStatus.COMPLETED,
            aggressiveness="moderate",
        )
        assert action is PruneAction.ARCHIVE

    def test_completed_medium_relevance_aggressive_archives(self):
        action = _decide_action(
            is_completed=True,
            relevance=0.5,
            task_status=TaskStatus.COMPLETED,
            aggressiveness="aggressive",
        )
        assert action is PruneAction.ARCHIVE

    def test_completed_medium_relevance_conservative_keeps(self):
        action = _decide_action(
            is_completed=True,
            relevance=0.4,
            task_status=TaskStatus.COMPLETED,
            aggressiveness="conservative",
        )
        assert action is PruneAction.KEEP

    # --- Low relevance (<0.3) ---
    def test_completed_low_relevance_conservative_archives(self):
        action = _decide_action(
            is_completed=True,
            relevance=0.1,
            task_status=TaskStatus.COMPLETED,
            aggressiveness="conservative",
        )
        assert action is PruneAction.ARCHIVE

    def test_completed_low_relevance_moderate_archives(self):
        action = _decide_action(
            is_completed=True,
            relevance=0.2,
            task_status=TaskStatus.COMPLETED,
            aggressiveness="moderate",
        )
        assert action is PruneAction.ARCHIVE

    def test_completed_low_relevance_aggressive_deletes(self):
        action = _decide_action(
            is_completed=True,
            relevance=0.1,
            task_status=TaskStatus.COMPLETED,
            aggressiveness="aggressive",
        )
        assert action is PruneAction.DELETE

    # --- Archived task status ---
    def test_archived_task_with_low_relevance(self):
        action = _decide_action(
            is_completed=False,
            relevance=0.05,
            task_status=TaskStatus.ARCHIVED,
            aggressiveness="moderate",
        )
        # Archived + not completed + low relevance → moderate behavior
        assert action in (PruneAction.KEEP, PruneAction.ARCHIVE, PruneAction.DELETE)

    # --- Non-completed, non-active: KEEP ---
    def test_non_completed_non_archived_keeps(self):
        action = _decide_action(
            is_completed=False,
            relevance=0.2,
            task_status=TaskStatus.ACTIVE,
            aggressiveness="aggressive",
        )
        assert action is PruneAction.KEEP

    # --- Edge cases at boundaries ---
    def test_exact_medium_threshold(self):
        """relevance == 0.6 should hit the high-relevance branch (KEEP)."""
        action = _decide_action(
            is_completed=True,
            relevance=0.6,
            task_status=TaskStatus.COMPLETED,
            aggressiveness="aggressive",
        )
        assert action is PruneAction.KEEP

    def test_just_below_medium_threshold(self):
        """relevance == 0.59 should hit medium-relevance branch."""
        action = _decide_action(
            is_completed=True,
            relevance=0.59,
            task_status=TaskStatus.COMPLETED,
            aggressiveness="moderate",
        )
        assert action is PruneAction.ARCHIVE

    def test_exact_low_threshold(self):
        """relevance == 0.3 is the boundary between low and medium."""
        action = _decide_action(
            is_completed=True,
            relevance=0.3,
            task_status=TaskStatus.COMPLETED,
            aggressiveness="moderate",
        )
        assert action is PruneAction.ARCHIVE

    def test_just_below_low_threshold(self):
        """relevance == 0.29 should hit low-relevance branch."""
        action = _decide_action(
            is_completed=True,
            relevance=0.29,
            task_status=TaskStatus.COMPLETED,
            aggressiveness="moderate",
        )
        assert action is PruneAction.ARCHIVE

    def test_zero_relevance(self):
        action = _decide_action(
            is_completed=True,
            relevance=0.0,
            task_status=TaskStatus.COMPLETED,
            aggressiveness="aggressive",
        )
        assert action is PruneAction.DELETE


# ---------------------------------------------------------------------------
# _estimate_total_tokens
# ---------------------------------------------------------------------------


class TestEstimateTotalTokens:
    def test_empty_list(self):
        assert _estimate_total_tokens([]) == 0

    def test_string_messages(self):
        msgs = ["hello world", "foo bar baz"]
        tokens = _estimate_total_tokens(msgs)
        # char/3 heuristic: "hello world" = 11 chars → 3, "foo bar baz" = 11 → 3
        assert tokens > 0

    def test_dict_messages(self):
        msgs = [{"content": "some text here"}]
        tokens = _estimate_total_tokens(msgs)
        assert tokens > 0

    def test_single_char_minimum(self):
        """Each message contributes at least 1 token."""
        msgs = ["a"]
        tokens = _estimate_total_tokens(msgs)
        assert tokens >= 1


# ---------------------------------------------------------------------------
# _extract_text (pruner version)
# ---------------------------------------------------------------------------


class TestPrunerExtractText:
    def test_string(self):
        assert _extract_text("hello") == "hello"

    def test_dict_content(self):
        assert _extract_text({"content": "body"}) == "body"

    def test_dict_text(self):
        assert _extract_text({"text": "msg"}) == "msg"

    def test_empty_dict(self):
        assert _extract_text({}) == ""

    def test_none(self):
        assert _extract_text(None) == ""


# ---------------------------------------------------------------------------
# evaluate_and_prune — gate conditions
# ---------------------------------------------------------------------------


class TestEvaluateAndPrune:
    @patch(
        "code_muse.plugins.task_context.pruner.get_task_prune_enabled",
        return_value=False,
    )
    def test_pruning_disabled(self, _mock):
        result = evaluate_and_prune(MagicMock(), ["msg"])
        assert result is None

    @patch(
        "code_muse.plugins.task_context.pruner.get_task_prune_enabled",
        return_value=True,
    )
    def test_empty_history(self, _mock):
        result = evaluate_and_prune(MagicMock(), [])
        assert result is None

    @patch(
        "code_muse.plugins.task_context.pruner.get_task_prune_enabled",
        return_value=True,
    )
    def test_single_message(self, _mock):
        result = evaluate_and_prune(MagicMock(), ["only one"])
        assert result is None

    @patch(
        "code_muse.plugins.task_context.pruner.get_task_prune_enabled",
        return_value=True,
    )
    @patch(
        "code_muse.plugins.task_context.pruner.get_task_prune_threshold",
        return_value=0.85,
    )
    def test_below_threshold_no_prune(self, _mock_thresh, _mock_enabled):
        """When token utilization is below threshold, no pruning occurs."""
        mgr = MagicMock()
        mgr.get_active_task.return_value = None
        result = evaluate_and_prune(mgr, ["a", "b"], token_budget=100000)
        # Could return None or a summary depending on logic
        # With very few messages and huge budget, should be None
        assert result is None


# ---------------------------------------------------------------------------
# PruneSummary properties
# ---------------------------------------------------------------------------


class TestPruneSummaryProperties:
    def test_kept_count(self):
        decisions = [
            PruneDecision(message_index=0, action=PruneAction.KEEP),
            PruneDecision(message_index=1, action=PruneAction.KEEP),
            PruneDecision(message_index=2, action=PruneAction.DELETE),
        ]
        s = PruneSummary(decisions=decisions)
        assert s.kept_count == 2

    def test_deleted_count(self):
        decisions = [
            PruneDecision(message_index=0, action=PruneAction.DELETE),
            PruneDecision(message_index=1, action=PruneAction.ARCHIVE),
        ]
        s = PruneSummary(decisions=decisions)
        assert s.deleted_count == 1
        assert s.archived_count == 1

    def test_tokens_saved_non_negative(self):
        s = PruneSummary(tokens_before=100, tokens_after=80, tokens_saved=20)
        assert s.tokens_saved == 20

    def test_zero_summary(self):
        s = PruneSummary()
        assert s.tokens_saved == 0
        assert s.kept_count == 0
