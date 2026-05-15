"""Integration tests for task_context.

Multi-task scenarios, rapid switching, complex state.
"""

from unittest.mock import patch

import pytest

from code_muse.plugins.task_context.completion import detect_completion
from code_muse.plugins.task_context.detector import detect_task_shift, reset_detector
from code_muse.plugins.task_context.models import (
    PruneAction,
    TaskStatus,
)
from code_muse.plugins.task_context.pruner import _decide_action, _estimate_total_tokens
from code_muse.plugins.task_context.task_manager import TaskManager


@pytest.fixture(autouse=True)
def _reset_detector():
    reset_detector()
    yield
    reset_detector()


# ---------------------------------------------------------------------------
# Multi-task conversation flow
# ---------------------------------------------------------------------------


class TestMultiTaskFlow:
    """Simulate a realistic multi-task conversation."""

    def test_full_lifecycle(self):
        mgr = TaskManager()

        # 1. Default task exists
        assert mgr.get_active_task() is not None
        initial_id = mgr.get_active_task_id()

        # 2. Tag some messages with default task
        msgs_1 = ["setup project", "configure linter"]
        mgr.tag_recent_messages(msgs_1, count=2)

        # 3. Start a new task
        task2_id = mgr.start_new_task(label="implement-auth")
        assert mgr.get_active_task_id() == task2_id
        assert mgr.get_task(initial_id).status is TaskStatus.COMPLETED

        # 4. Tag messages for task 2
        msgs_2 = ["create login page", "add JWT tokens"]
        mgr.tag_recent_messages(msgs_2, count=2)

        # 5. Complete task 2
        mgr.complete_current_task(outcome="Auth module complete")

        # 6. Start task 3
        task3_id = mgr.start_new_task(label="write-tests")

        # 7. Verify state
        all_tasks = mgr.get_all_tasks()
        assert len(all_tasks) == 3

        completed = mgr.get_completed_tasks()
        # initial + task2 are completed
        assert len(completed) == 2

        # Only task3 is active
        assert mgr.get_active_task_id() == task3_id

    def test_task_cross_references_across_flow(self):
        mgr = TaskManager()
        t1 = mgr.get_active_task_id()
        t2 = mgr.start_new_task(label="feature")
        t3 = mgr.start_new_task(label="bugfix")

        # t3 cross-references t1 and t2
        mgr.add_cross_reference(t1, t3)
        mgr.add_cross_reference(t2, t3)

        xrefs = mgr.get_cross_referenced_tasks(t3)
        assert len(xrefs) == 2

        # t2 should also reference t3
        xrefs_t2 = mgr.get_cross_referenced_tasks(t2)
        assert any(x.task_id == t3 for x in xrefs_t2)

    def test_archiving_flow(self):
        mgr = TaskManager()
        t1 = mgr.get_active_task_id()
        mgr.start_new_task(label="new-task")

        # Archive t1
        assert mgr.mark_task_archived(t1) is True
        assert mgr.get_task(t1).status is TaskStatus.ARCHIVED
        assert len(mgr.get_archived_tasks()) == 1

        # Archiving nonexistent task
        assert mgr.mark_task_archived("ghost") is False


# ---------------------------------------------------------------------------
# Rapid task switching
# ---------------------------------------------------------------------------


class TestRapidTaskSwitching:
    def test_many_rapid_switches(self):
        mgr = TaskManager()
        ids = []
        for i in range(10):
            tid = mgr.start_new_task(label=f"task-{i}")
            ids.append(tid)

        # Only the last task should be active
        assert mgr.get_active_task_id() == ids[-1]

        # All previous should be completed
        for tid in ids[:-1]:
            task = mgr.get_task(tid)
            assert task.status is TaskStatus.COMPLETED

    def test_switch_then_complete(self):
        mgr = TaskManager()
        mgr.start_new_task(label="first")
        mgr.start_new_task(label="second")
        # Complete the current active task
        mgr.complete_current_task(outcome="done")
        # No active task now
        assert mgr.get_active_task_id() is not None
        # The task was completed
        t2 = mgr.get_task(mgr.get_active_task_id())
        assert t2.status is TaskStatus.COMPLETED


# ---------------------------------------------------------------------------
# Serialization with complex state
# ---------------------------------------------------------------------------


class TestComplexSerialization:
    def test_round_trip_with_multiple_tasks_and_tags(self):
        mgr = TaskManager()
        # Default task + tags
        msgs_1 = ["a", "b", "c"]
        mgr.tag_recent_messages(msgs_1, count=3)

        # Start task 2 with tags
        t2 = mgr.start_new_task(label="second")
        msgs_2 = ["d", "e"]
        mgr.tag_recent_messages(msgs_2, count=2)

        # Add cross-reference
        t1 = mgr.get_all_tasks()[0].task_id
        mgr.add_cross_reference(t1, t2)

        # Serialize
        data = mgr.to_dict()

        # Deserialize
        mgr2 = TaskManager.from_dict(data)

        # Verify structure
        assert len(mgr2.get_all_tasks()) == len(mgr.get_all_tasks())
        assert mgr2.get_active_task().label == "second"

        # Cross-references preserved
        xrefs = mgr2.get_cross_referenced_tasks(t2)
        assert len(xrefs) == 1

    def test_round_trip_preserves_token_counts(self):
        mgr = TaskManager()
        t1 = mgr.get_active_task_id()
        mgr.update_token_count(t1, 7500)

        data = mgr.to_dict()
        mgr2 = TaskManager.from_dict(data)

        task = mgr2.get_task(t1)
        assert task.token_count == 7500

    def test_round_trip_preserves_completed_at(self):
        mgr = TaskManager()
        t1 = mgr.get_active_task_id()
        mgr.start_new_task(label="next")
        # t1 should have completed_at
        data = mgr.to_dict()
        mgr2 = TaskManager.from_dict(data)
        restored = mgr2.get_task(t1)
        assert restored.completed_at is not None


# ---------------------------------------------------------------------------
# Detector + TaskManager integration
# ---------------------------------------------------------------------------


class TestDetectorTaskManagerIntegration:
    @patch(
        "code_muse.plugins.task_context.detector.get_task_auto_detect",
        return_value=True,
    )
    def test_detect_and_create_task(self, _mock):
        mgr = TaskManager()
        sig = detect_task_shift("let's start a new task: refactor auth", [])

        if sig.detected and sig.suggested_label:
            new_id = mgr.start_new_task(
                label=sig.suggested_label,
                from_signal=sig.signal_source,
            )
            task = mgr.get_task(new_id)
            assert task.label == sig.suggested_label
            assert task.auto_detected is True


# ---------------------------------------------------------------------------
# Completion + TaskManager integration
# ---------------------------------------------------------------------------


class TestCompletionTaskManagerIntegration:
    @patch(
        "code_muse.plugins.task_context.completion.get_task_auto_complete_timeout",
        return_value=600,
    )
    def test_detect_and_complete(self, _mock):
        mgr = TaskManager()
        mgr.start_new_task(label="refactor")

        sig = detect_completion(
            task_manager=mgr,
            response_text="Successfully refactored the auth module",
            user_message="task done",
        )
        if sig.detected:
            mgr.complete_current_task(outcome=sig.outcome_summary)

        completed = mgr.get_completed_tasks()
        assert len(completed) >= 1


# ---------------------------------------------------------------------------
# Pruner + TaskManager integration
# ---------------------------------------------------------------------------


class TestPrunerTaskManagerIntegration:
    def test_decide_action_for_completed_tasks(self):
        """Verify pruning decisions across various task states."""
        # Completed + high relevance → KEEP
        assert (
            _decide_action(True, 0.8, TaskStatus.COMPLETED, "moderate")
            is PruneAction.KEEP
        )

        # Completed + low relevance + aggressive → DELETE
        assert (
            _decide_action(True, 0.1, TaskStatus.COMPLETED, "aggressive")
            is PruneAction.DELETE
        )

        # Completed + medium relevance + conservative → KEEP
        assert (
            _decide_action(True, 0.4, TaskStatus.COMPLETED, "conservative")
            is PruneAction.KEEP
        )

        # Active → always KEEP
        assert (
            _decide_action(False, 0.05, TaskStatus.ACTIVE, "aggressive")
            is PruneAction.KEEP
        )


# ---------------------------------------------------------------------------
# End-to-end scenario
# ---------------------------------------------------------------------------


class TestEndToEnd:
    def test_three_task_scenario(self):
        """Full scenario: setup → feature → bugfix with archival."""
        mgr = TaskManager()

        # Phase 1: Setup
        initial_id = mgr.get_active_task_id()
        setup_msgs = ["create project", "add dependencies", "configure CI"]
        mgr.tag_recent_messages(setup_msgs, count=3)
        mgr.update_token_count(initial_id, 1500)

        # Phase 2: Feature work
        feature_id = mgr.start_new_task(label="add-user-model")
        feature_msgs = ["define schema", "write migrations"]
        mgr.tag_recent_messages(feature_msgs, count=2)
        mgr.update_token_count(feature_id, 2000)
        mgr.complete_current_task(outcome="User model implemented")

        # Phase 3: Bugfix
        bugfix_id = mgr.start_new_task(label="fix-login-bug")
        bugfix_msgs = ["reproduce bug", "fix the issue"]
        mgr.tag_recent_messages(bugfix_msgs, count=2)
        mgr.update_token_count(bugfix_id, 800)

        # Cross-reference bugfix to feature (they share auth context)
        mgr.add_cross_reference(feature_id, bugfix_id)

        # Archive the completed feature task
        mgr.mark_task_archived(feature_id)

        # Verify final state
        assert len(mgr.get_archived_tasks()) == 1
        assert mgr.get_active_task().label == "fix-login-bug"

        # Round-trip serialization
        data = mgr.to_dict()
        mgr2 = TaskManager.from_dict(data)
        assert mgr2.get_active_task().label == "fix-login-bug"
        assert len(mgr2.get_archived_tasks()) == 1

    def test_token_estimation_across_tasks(self):
        """Verify token estimation works with mixed message types."""
        mgr = TaskManager()
        initial_id = mgr.get_active_task_id()

        messages = [
            {"content": "Setting up the project structure"},
            {"content": "Adding configuration files"},
            "plain string message",
        ]
        mgr.tag_recent_messages(messages, count=3)

        tokens = _estimate_total_tokens(messages)
        assert tokens > 0

        mgr.update_token_count(initial_id, tokens)
        assert mgr.get_task(initial_id).token_count == tokens
