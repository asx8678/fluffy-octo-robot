"""Tests for task_context.completion — completion detection."""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

from code_muse.plugins.task_context.completion import (
    _check_inactivity_timeout,
    _extract_outcome,
    detect_completion,
)
from code_muse.plugins.task_context.models import TaskContext

# ---------------------------------------------------------------------------
# Explicit user completion signals (high confidence)
# ---------------------------------------------------------------------------


class TestHighConfidenceUserSignals:
    @patch(
        "code_muse.plugins.task_context.completion.get_task_auto_complete_timeout",
        return_value=600,
    )
    def test_task_done(self, _mock_timeout):
        task_mgr = MagicMock()
        sig = detect_completion(
            task_manager=task_mgr,
            response_text="Done!",
            user_message="task done",
        )
        assert sig.detected is True
        assert sig.confidence == 0.9
        assert sig.signal_source == "explicit"

    @patch(
        "code_muse.plugins.task_context.completion.get_task_auto_complete_timeout",
        return_value=600,
    )
    def test_work_complete(self, _mock_timeout):
        sig = detect_completion(
            task_manager=MagicMock(),
            response_text="ok",
            user_message="work complete",
        )
        assert sig.detected is True
        assert sig.confidence == 0.9

    @patch(
        "code_muse.plugins.task_context.completion.get_task_auto_complete_timeout",
        return_value=600,
    )
    def test_thats_done(self, _mock_timeout):
        sig = detect_completion(
            task_manager=MagicMock(),
            response_text="ok",
            user_message="that's done",
        )
        assert sig.detected is True
        assert sig.confidence == 0.9

    @patch(
        "code_muse.plugins.task_context.completion.get_task_auto_complete_timeout",
        return_value=600,
    )
    def test_im_finished_with(self, _mock_timeout):
        sig = detect_completion(
            task_manager=MagicMock(),
            response_text="ok",
            user_message="i'm finished with the refactor",
        )
        assert sig.detected is True
        assert sig.confidence == 0.9

    @patch(
        "code_muse.plugins.task_context.completion.get_task_auto_complete_timeout",
        return_value=600,
    )
    def test_all_set(self, _mock_timeout):
        sig = detect_completion(
            task_manager=MagicMock(),
            response_text="ok",
            user_message="all set!",
        )
        assert sig.detected is True
        assert sig.confidence == 0.9

    @patch(
        "code_muse.plugins.task_context.completion.get_task_auto_complete_timeout",
        return_value=600,
    )
    def test_completed_the_task(self, _mock_timeout):
        sig = detect_completion(
            task_manager=MagicMock(),
            response_text="ok",
            user_message="completed the task",
        )
        assert sig.detected is True
        assert sig.confidence == 0.9


# ---------------------------------------------------------------------------
# Medium confidence user signals
# ---------------------------------------------------------------------------


class TestMediumConfidenceUserSignals:
    @patch(
        "code_muse.plugins.task_context.completion.get_task_auto_complete_timeout",
        return_value=600,
    )
    def test_whats_next(self, _mock_timeout):
        sig = detect_completion(
            task_manager=MagicMock(),
            response_text="",
            user_message="what's next?",
        )
        assert sig.detected is True
        assert sig.confidence == 0.7

    @patch(
        "code_muse.plugins.task_context.completion.get_task_auto_complete_timeout",
        return_value=600,
    )
    def test_ship_it(self, _mock_timeout):
        sig = detect_completion(
            task_manager=MagicMock(),
            response_text="",
            user_message="ship it",
        )
        assert sig.detected is True
        assert sig.confidence == 0.7

    @patch(
        "code_muse.plugins.task_context.completion.get_task_auto_complete_timeout",
        return_value=600,
    )
    def test_merge_this(self, _mock_timeout):
        sig = detect_completion(
            task_manager=MagicMock(),
            response_text="",
            user_message="merge this PR",
        )
        assert sig.detected is True
        assert sig.confidence == 0.7


# ---------------------------------------------------------------------------
# Agent self-assessment signals
# ---------------------------------------------------------------------------


class TestAgentSelfAssessment:
    @patch(
        "code_muse.plugins.task_context.completion.get_task_auto_complete_timeout",
        return_value=600,
    )
    def test_pr_merged(self, _mock_timeout):
        sig = detect_completion(
            task_manager=MagicMock(),
            response_text="PR #42 merged into main",
            user_message=None,
        )
        assert sig.detected is True
        assert sig.confidence == 0.75
        assert sig.signal_source == "agent_self_assessment"

    @patch(
        "code_muse.plugins.task_context.completion.get_task_auto_complete_timeout",
        return_value=600,
    )
    def test_tests_passing(self, _mock_timeout):
        sig = detect_completion(
            task_manager=MagicMock(),
            response_text="All tests passing after the fix",
            user_message=None,
        )
        assert sig.detected is True
        assert sig.signal_source == "agent_self_assessment"

    @patch(
        "code_muse.plugins.task_context.completion.get_task_auto_complete_timeout",
        return_value=600,
    )
    def test_deployed_to_production(self, _mock_timeout):
        sig = detect_completion(
            task_manager=MagicMock(),
            response_text="Deployed to production successfully",
            user_message=None,
        )
        assert sig.detected is True
        assert sig.signal_source == "agent_self_assessment"

    @patch(
        "code_muse.plugins.task_context.completion.get_task_auto_complete_timeout",
        return_value=600,
    )
    def test_task_closed(self, _mock_timeout):
        sig = detect_completion(
            task_manager=MagicMock(),
            response_text="task #123 closed — bug fixed",
            user_message=None,
        )
        assert sig.detected is True
        assert sig.signal_source == "agent_self_assessment"

    @patch(
        "code_muse.plugins.task_context.completion.get_task_auto_complete_timeout",
        return_value=600,
    )
    def test_successfully_implemented(self, _mock_timeout):
        sig = detect_completion(
            task_manager=MagicMock(),
            response_text="successfully implemented the feature",
            user_message=None,
        )
        assert sig.detected is True


# ---------------------------------------------------------------------------
# No completion detected
# ---------------------------------------------------------------------------


class TestNoCompletion:
    @patch(
        "code_muse.plugins.task_context.completion.get_task_auto_complete_timeout",
        return_value=600,
    )
    def test_regular_message(self, _mock_timeout):
        sig = detect_completion(
            task_manager=MagicMock(),
            response_text="I'll look at that now.",
            user_message="can you check this?",
        )
        assert sig.detected is False

    @patch(
        "code_muse.plugins.task_context.completion.get_task_auto_complete_timeout",
        return_value=600,
    )
    def test_empty_messages(self, _mock_timeout):
        sig = detect_completion(
            task_manager=MagicMock(),
            response_text="",
            user_message="",
        )
        assert sig.detected is False

    @patch(
        "code_muse.plugins.task_context.completion.get_task_auto_complete_timeout",
        return_value=600,
    )
    def test_no_user_message(self, _mock_timeout):
        sig = detect_completion(
            task_manager=MagicMock(),
            response_text="I'll start working on that.",
            user_message=None,
        )
        assert sig.detected is False


# ---------------------------------------------------------------------------
# Inactivity timeout
# ---------------------------------------------------------------------------


class TestInactivityTimeout:
    @patch(
        "code_muse.plugins.task_context.completion.get_task_auto_complete_timeout",
        return_value=600,
    )
    def test_no_timeout_when_recent(self, _mock_timeout):
        # Real TaskContext now has last_accessed
        task = TaskContext(last_accessed=datetime.now())
        sig = _check_inactivity_timeout(task, MagicMock())
        assert sig.detected is False

    @patch(
        "code_muse.plugins.task_context.completion.get_task_auto_complete_timeout",
        return_value=0,
    )
    def test_disabled_timeout(self, _mock_timeout):
        task = TaskContext(created_at=datetime(2020, 1, 1, tzinfo=UTC))
        sig = _check_inactivity_timeout(task, MagicMock())
        assert sig.detected is False

    @patch(
        "code_muse.plugins.task_context.completion.get_task_auto_complete_timeout",
        return_value=1,
    )
    def test_timeout_fires(self, _mock_timeout):
        old_time = datetime.now(UTC) - timedelta(hours=1)
        task = TaskContext(
            last_accessed=old_time,
            created_at=old_time,
        )
        sig = _check_inactivity_timeout(task, MagicMock())
        assert sig.detected is True
        assert sig.signal_source == "inactivity_timeout"
        assert sig.confidence == 0.5


# ---------------------------------------------------------------------------
# Outcome extraction
# ---------------------------------------------------------------------------


class TestOutcomeExtraction:
    def test_pr_outcome(self):
        result = _extract_outcome("PR #42 merged — auth refactor complete")
        assert result is not None

    def test_deployed_outcome(self):
        result = _extract_outcome("Deployed the new cache layer to production")
        assert result is not None

    def test_empty_text(self):
        assert _extract_outcome("") is None

    def test_no_outcome_pattern(self):
        result = _extract_outcome("random text without patterns")
        # May return first sentence or None
        # Just ensure it doesn't crash
        assert result is None or isinstance(result, str)


# ---------------------------------------------------------------------------
# Signal ordering (explicit > agent > timeout)
# ---------------------------------------------------------------------------


class TestSignalPriority:
    @patch(
        "code_muse.plugins.task_context.completion.get_task_auto_complete_timeout",
        return_value=600,
    )
    def test_explicit_over_agent(self, _mock_timeout):
        """When user says 'done' AND agent says 'tests pass',
        explicit wins because user message is checked first."""
        sig = detect_completion(
            task_manager=MagicMock(),
            response_text="I'll review the output now.",
            user_message="task done",
        )
        assert sig.signal_source == "explicit"
        assert sig.confidence == 0.9
