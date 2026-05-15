"""Tests for task_context.task_manager.

Lifecycle, tagging, cross-refs, serialization.
"""

import threading

from code_muse.plugins.task_context.models import TaskStatus
from code_muse.plugins.task_context.task_manager import TaskManager

# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------


class TestTaskManagerInit:
    def test_creates_default_task(self):
        mgr = TaskManager()
        active = mgr.get_active_task()
        assert active is not None
        assert active.label == "initial-context"
        assert active.status is TaskStatus.ACTIVE
        assert active.auto_detected is True

    def test_active_task_id_set(self):
        mgr = TaskManager()
        assert mgr.get_active_task_id() is not None

    def test_initial_task_count(self):
        mgr = TaskManager()
        all_tasks = mgr.get_all_tasks()
        assert len(all_tasks) == 1


# ---------------------------------------------------------------------------
# Task lifecycle
# ---------------------------------------------------------------------------


class TestStartNewTask:
    def test_starts_new_task_with_label(self):
        mgr = TaskManager()
        task_id = mgr.start_new_task(label="refactor-auth")
        assert task_id is not None
        task = mgr.get_task(task_id)
        assert task is not None
        assert task.label == "refactor-auth"
        assert task.status is TaskStatus.ACTIVE

    def test_completes_previous_active_task(self):
        mgr = TaskManager()
        initial_id = mgr.get_active_task_id()
        mgr.start_new_task(label="new-thing")
        # The initial task should now be completed
        initial = mgr.get_task(initial_id)
        assert initial is not None
        assert initial.status is TaskStatus.COMPLETED
        assert initial.completed_at is not None

    def test_auto_label_when_no_label(self):
        mgr = TaskManager()
        task_id = mgr.start_new_task()
        task = mgr.get_task(task_id)
        assert task.label.startswith("task-")

    def test_auto_detected_flag(self):
        mgr = TaskManager()
        task_id = mgr.start_new_task(from_signal="keyword match")
        task = mgr.get_task(task_id)
        assert task.auto_detected is True

    def test_explicit_task_not_auto_detected(self):
        mgr = TaskManager()
        task_id = mgr.start_new_task(label="manual-task")
        task = mgr.get_task(task_id)
        assert task.auto_detected is False

    def test_active_task_changes(self):
        mgr = TaskManager()
        first_id = mgr.start_new_task(label="first")
        second_id = mgr.start_new_task(label="second")
        assert mgr.get_active_task_id() == second_id
        assert mgr.get_active_task_id() != first_id


class TestCompleteCurrentTask:
    def test_completes_active_task(self):
        mgr = TaskManager()
        mgr.start_new_task(label="do-something")
        result = mgr.complete_current_task(outcome="PR merged")
        assert result == "PR merged"
        active = mgr.get_active_task()
        assert active is None or active.status != TaskStatus.ACTIVE

    def test_outcome_stored(self):
        mgr = TaskManager()
        mgr.start_new_task(label="work")
        mgr.complete_current_task(outcome="All tests pass")
        completed = mgr.get_completed_tasks()
        assert any(t.outcome_summary == "All tests pass" for t in completed)

    def test_returns_none_when_no_active_task(self):
        mgr = TaskManager()
        mgr.complete_current_task()  # Complete the default task
        # Now complete again — should return None (no active task)
        result = mgr.complete_current_task()
        assert result is None

    def test_no_outcome_returns_none(self):
        mgr = TaskManager()
        mgr.start_new_task(label="no-outcome")
        result = mgr.complete_current_task()
        assert result is None

    def test_completed_at_set(self):
        mgr = TaskManager()
        mgr.start_new_task(label="timing")
        mgr.complete_current_task()
        completed = mgr.get_completed_tasks()
        # Both initial-context and "timing" are completed
        assert len(completed) == 2
        for t in completed:
            assert t.completed_at is not None


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------


class TestGetCompletedTasks:
    def test_returns_only_completed(self):
        mgr = TaskManager()
        mgr.start_new_task(label="a")
        mgr.start_new_task(label="b")
        completed = mgr.get_completed_tasks()
        for t in completed:
            assert t.status is TaskStatus.COMPLETED

    def test_completed_count(self):
        mgr = TaskManager()
        mgr.start_new_task(label="x")  # initial → completed
        mgr.start_new_task(label="y")  # x → completed
        # initial + x are completed
        completed = mgr.get_completed_tasks()
        assert len(completed) == 2


class TestGetArchivedTasks:
    def test_returns_only_archived(self):
        mgr = TaskManager()
        tid = mgr.get_active_task_id()
        mgr.mark_task_archived(tid)
        archived = mgr.get_archived_tasks()
        assert len(archived) == 1
        assert archived[0].status is TaskStatus.ARCHIVED


class TestGetAllTasks:
    def test_sorted_by_created_at(self):
        mgr = TaskManager()
        mgr.start_new_task(label="second")
        tasks = mgr.get_all_tasks()
        for i in range(len(tasks) - 1):
            assert tasks[i].created_at <= tasks[i + 1].created_at


# ---------------------------------------------------------------------------
# Message tagging
# ---------------------------------------------------------------------------


class TestMessageTagging:
    def test_tag_recent_messages(self):
        mgr = TaskManager()
        msgs = ["hello", "world", "foo"]
        mgr.tag_recent_messages(msgs, count=2)
        task = mgr.get_active_task()
        assert task.message_count == 2

    def test_no_duplicate_tagging(self):
        mgr = TaskManager()
        msgs = ["hello", "world"]
        mgr.tag_recent_messages(msgs, count=2)
        mgr.tag_recent_messages(msgs, count=2)  # Same objects → no re-tag
        task = mgr.get_active_task()
        assert task.message_count == 2

    def test_get_task_for_message(self):
        mgr = TaskManager()
        msgs = ["a", "b", "c"]
        mgr.tag_recent_messages(msgs, count=3)
        active_id = mgr.get_active_task_id()
        for i in range(3):
            assert mgr.get_task_for_message(i) == active_id

    def test_get_task_message_indices(self):
        mgr = TaskManager()
        msgs = ["x", "y", "z"]
        mgr.tag_recent_messages(msgs, count=3)
        active_id = mgr.get_active_task_id()
        indices = mgr.get_task_message_indices(active_id)
        assert sorted(indices) == [0, 1, 2]

    def test_tag_with_empty_history(self):
        mgr = TaskManager()
        mgr.tag_recent_messages([], count=1)
        task = mgr.get_active_task()
        assert task.message_count == 0


# ---------------------------------------------------------------------------
# Cross-reference tracking
# ---------------------------------------------------------------------------


class TestCrossReferences:
    def test_add_cross_reference(self):
        mgr = TaskManager()
        t1 = mgr.get_active_task_id()
        t2 = mgr.start_new_task(label="second")
        mgr.add_cross_reference(t1, t2)
        task1 = mgr.get_task(t1)
        task2 = mgr.get_task(t2)
        assert t2 in task1.cross_referenced_task_ids
        assert t1 in task2.cross_referenced_task_ids

    def test_get_cross_referenced_tasks(self):
        mgr = TaskManager()
        t1 = mgr.get_active_task_id()
        t2 = mgr.start_new_task(label="second")
        mgr.add_cross_reference(t1, t2)
        xrefs = mgr.get_cross_referenced_tasks(t2)
        assert len(xrefs) == 1
        assert xrefs[0].task_id == t1

    def test_cross_ref_with_unknown_task(self):
        mgr = TaskManager()
        # Should not raise
        mgr.add_cross_reference("nonexistent", "also-nonexistent")

    def test_get_cross_refs_for_unknown_task(self):
        mgr = TaskManager()
        assert mgr.get_cross_referenced_tasks("ghost") == []


# ---------------------------------------------------------------------------
# Token tracking
# ---------------------------------------------------------------------------


class TestTokenTracking:
    def test_update_token_count(self):
        mgr = TaskManager()
        tid = mgr.get_active_task_id()
        mgr.update_token_count(tid, 5000)
        task = mgr.get_task(tid)
        assert task.token_count == 5000

    def test_update_nonexistent_task(self):
        mgr = TaskManager()
        # Should not raise
        mgr.update_token_count("nope", 100)


# ---------------------------------------------------------------------------
# Serialization round-trip
# ---------------------------------------------------------------------------


class TestSerialization:
    def test_round_trip_basic(self):
        mgr = TaskManager()
        mgr.start_new_task(label="first-task")
        mgr.start_new_task(label="second-task")
        data = mgr.to_dict()
        mgr2 = TaskManager.from_dict(data)
        assert mgr2.get_active_task_id() is not None
        assert mgr2.get_active_task().label == "second-task"
        assert len(mgr2.get_all_tasks()) == 3

    def test_round_trip_with_tagged_messages(self):
        mgr = TaskManager()
        msgs = ["alpha", "beta", "gamma"]
        mgr.tag_recent_messages(msgs, count=3)
        data = mgr.to_dict()
        mgr2 = TaskManager.from_dict(data)
        active_id = mgr2.get_active_task_id()
        assert mgr2.get_task_for_message(0) == active_id

    def test_round_trip_with_cross_refs(self):
        mgr = TaskManager()
        t1 = mgr.get_active_task_id()
        t2 = mgr.start_new_task(label="cross-linked")
        mgr.add_cross_reference(t1, t2)
        data = mgr.to_dict()
        mgr2 = TaskManager.from_dict(data)
        xrefs = mgr2.get_cross_referenced_tasks(t2)
        assert len(xrefs) == 1

    def test_from_dict_none(self):
        mgr = TaskManager.from_dict(None)
        # Should create fresh manager with default task
        assert mgr.get_active_task() is not None

    def test_from_dict_empty(self):
        # Empty dict is falsy in Python, so from_dict({}) returns
        # a fresh manager with the default initial task
        mgr = TaskManager.from_dict({})
        assert mgr.get_active_task() is not None
        assert mgr.get_active_task().label == "initial-context"

    def test_version_field(self):
        mgr = TaskManager()
        data = mgr.to_dict()
        assert data["version"] == 1


# ---------------------------------------------------------------------------
# Thread safety (smoke test)
# ---------------------------------------------------------------------------


class TestThreadSafety:
    def test_concurrent_task_creation(self):
        mgr = TaskManager()
        results: list[str] = []
        errors: list[Exception] = []

        def create_task(label: str):
            try:
                tid = mgr.start_new_task(label=label)
                results.append(tid)
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=create_task, args=(f"t-{i}",)) for i in range(5)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        assert len(results) == 5
