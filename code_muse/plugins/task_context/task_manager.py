"""TaskManager — central registry for task lifecycle management.

Manages task creation, completion, archiving, and recall.
Thread-safe via threading.Lock for concurrent access.
"""

import contextlib
import logging
import threading
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from code_muse.plugins.task_context.models import (
    TaskContext,
    TaskStatus,
)

logger = logging.getLogger(__name__)


class TaskManager:
    """Central registry for all tasks in the current session.

    Thread-safe singleton that manages the full lifecycle of tasks:
    - Creating new tasks (explicit or auto-detected)
    - Tracking task message count and token usage
    - Marking tasks complete
    - Archiving completed tasks
    - Recalling archived tasks
    - Tagging messages with task metadata
    - Cross-reference tracking

    Usage:
        manager = TaskManager()
        task_id = manager.start_new_task(label="refactor-auth")
        manager.tag_recent_messages(message_history, count=3)
        manager.complete_current_task(outcome="PR #456 merged")
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # task_id -> TaskContext
        self._tasks: dict[str, TaskContext] = {}
        # message_index -> task_id mapping for quick lookups
        self._message_task_map: dict[int, str] = {}
        # message_task_tags: message identity hash -> task_id for dedup tagging
        self._tagged_message_hashes: set[int] = set()
        self._active_task_id: str | None = None
        self._task_counter: int = 0
        self._initialized = False
        self._initialize_default()

    def _initialize_default(self) -> None:
        """Create the initial default task on first use."""
        if not self._initialized:
            self._initialized = True
            task_id = self._generate_task_id()
            task = TaskContext(
                task_id=task_id,
                label="initial-context",
                status=TaskStatus.ACTIVE,
                auto_detected=True,
            )
            self._tasks[task_id] = task
            self._active_task_id = task_id
            logger.debug("Initialized default task: %s", task_id)

    def _generate_task_id(self) -> str:
        """Generate a unique, sortable task ID."""
        timestamp = datetime.now(UTC).strftime("%y%m%d%H%M%S")
        short_id = str(uuid4())[:8]
        return f"task_{timestamp}_{short_id}"

    # ------------------------------------------------------------------
    # Public API: Task lifecycle
    # ------------------------------------------------------------------

    def start_new_task(
        self,
        label: str | None = None,
        from_signal: str | None = None,
    ) -> str:
        """Start a new task, archiving the current active task.

        Args:
            label: Optional human-readable label for the new task.
            from_signal: Optional description of what triggered the new task.

        Returns:
            The new task_id.
        """
        with self._lock:
            # Complete the current active task if it exists
            if self._active_task_id and self._active_task_id in self._tasks:
                current = self._tasks[self._active_task_id]
                if current.status == TaskStatus.ACTIVE:
                    current.status = TaskStatus.COMPLETED
                    current.completed_at = datetime.now()

            # Create the new task
            self._task_counter += 1
            task_id = self._generate_task_id()
            task = TaskContext(
                task_id=task_id,
                label=label or f"task-{self._task_counter}",
                status=TaskStatus.ACTIVE,
                auto_detected=(from_signal is not None),
            )
            self._tasks[task_id] = task
            self._active_task_id = task_id

            source_info = f" (from: {from_signal})" if from_signal else ""
            logger.info(
                "Started new task '%s' [%s]%s",
                task.label,
                task_id[:8],
                source_info,
            )
            return task_id

    def complete_current_task(self, outcome: str | None = None) -> str | None:
        """Mark the current active task as completed.

        Args:
            outcome: Optional one-line summary of what was accomplished.

        Returns:
            The outcome summary if one was set, or None.
        """
        with self._lock:
            if not self._active_task_id:
                logger.debug("No active task to complete")
                return None

            task = self._tasks.get(self._active_task_id)
            if not task or task.status != TaskStatus.ACTIVE:
                return None

            task.status = TaskStatus.COMPLETED
            task.completed_at = datetime.now()
            if outcome:
                task.outcome_summary = outcome

            logger.info(
                "Task '%s' [%s] completed: %s",
                task.label,
                task.task_id[:8],
                outcome or "no summary",
            )
            return outcome

    def get_active_task(self) -> TaskContext | None:
        """Return the current active task context, or None."""
        with self._lock:
            if self._active_task_id:
                return self._tasks.get(self._active_task_id)
            return None

    def get_task(self, task_id: str) -> TaskContext | None:
        """Return a specific task by ID."""
        with self._lock:
            return self._tasks.get(task_id)

    def get_all_tasks(self) -> list[TaskContext]:
        """Return all tasks, sorted by creation time."""
        with self._lock:
            return sorted(
                list(self._tasks.values()),
                key=lambda t: t.created_at,
            )

    def get_completed_tasks(self) -> list[TaskContext]:
        """Return all completed (not active, not archived) tasks."""
        with self._lock:
            return [t for t in self._tasks.values() if t.status == TaskStatus.COMPLETED]

    def get_active_task_id(self) -> str | None:
        """Return the current active task ID."""
        with self._lock:
            return self._active_task_id

    def get_archived_tasks(self) -> list[TaskContext]:
        """Return all archived tasks."""
        with self._lock:
            return [t for t in self._tasks.values() if t.status == TaskStatus.ARCHIVED]

    def mark_task_archived(self, task_id: str) -> bool:
        """Mark a task as archived (after its messages are persisted to cold storage).

        Returns True if the task was found and marked.
        """
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return False
            task.status = TaskStatus.ARCHIVED
            return True

    # ------------------------------------------------------------------
    # Message tagging
    # ------------------------------------------------------------------

    def tag_recent_messages(
        self,
        message_history: list[Any],
        count: int = 1,
    ) -> None:
        """Tag the most recent N messages with the active task_id.

        This is called after new messages are added to the history.
        Uses message hash to avoid duplicate tagging.

        Args:
            message_history: The full message history list.
            count: Number of most recent messages to tag.
        """
        with self._lock:
            if not self._active_task_id:
                return
            task = self._tasks.get(self._active_task_id)
            if not task:
                return

            start = max(0, len(message_history) - count)
            tag_count = 0
            for i in range(start, len(message_history)):
                msg = message_history[i]
                msg_hash = id(msg)
                if msg_hash not in self._tagged_message_hashes:
                    self._tagged_message_hashes.add(msg_hash)
                    self._message_task_map[i] = self._active_task_id
                    task.message_count += 1
                    tag_count += 1

            if tag_count > 0:
                logger.debug("Tagged %d messages with task '%s'", tag_count, task.label)

    def get_task_for_message(self, message_index: int) -> str | None:
        """Return the task_id for a given message index."""
        with self._lock:
            return self._message_task_map.get(message_index)

    def get_task_message_indices(self, task_id: str) -> list[int]:
        """Return all message indices tagged with the given task_id."""
        with self._lock:
            return [
                idx for idx, tid in self._message_task_map.items() if tid == task_id
            ]

    # ------------------------------------------------------------------
    # Cross-task reference tracking
    # ------------------------------------------------------------------

    def add_cross_reference(self, source_task_id: str, target_task_id: str) -> None:
        """Record a cross-reference between two tasks.

        Called when a message from a completed task is referenced by the
        active task, ensuring it's not fully pruned.
        """
        with self._lock:
            source = self._tasks.get(source_task_id)
            target = self._tasks.get(target_task_id)
            if source and target:
                source.cross_referenced_task_ids.add(target_task_id)
                target.cross_referenced_task_ids.add(source_task_id)

    def get_cross_referenced_tasks(self, task_id: str) -> list[TaskContext]:
        """Return all tasks cross-referenced with the given task."""
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return []
            return [
                self._tasks[tid]
                for tid in task.cross_referenced_task_ids
                if tid in self._tasks
            ]

    # ------------------------------------------------------------------
    # Token tracking
    # ------------------------------------------------------------------

    def update_token_count(self, task_id: str, tokens: int) -> None:
        """Update the estimated token count for a task."""
        with self._lock:
            task = self._tasks.get(task_id)
            if task:
                task.token_count = tokens

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        """Serialize the task manager state for session storage.

        Returns a dict suitable for storing as task_context in session JSON.
        """
        with self._lock:
            return {
                "version": 1,
                "active_task_id": self._active_task_id,
                "task_counter": self._task_counter,
                "tasks": {
                    tid: task.model_dump(mode="json")
                    for tid, task in self._tasks.items()
                },
                "message_task_map": {
                    str(idx): tid for idx, tid in self._message_task_map.items()
                },
                "tagged_message_hashes": list(self._tagged_message_hashes),
            }

    @classmethod
    def from_dict(cls, data: dict | None) -> TaskManager:
        """Restore a TaskManager from serialized state.

        Args:
            data: Dict previously returned by to_dict(), or None for fresh start.

        Returns:
            A TaskManager instance with restored state.
        """
        manager = cls()
        if not data:
            return manager

        with manager._lock:
            # Clear the default task created by __init__
            manager._tasks.clear()
            manager._message_task_map.clear()
            manager._tagged_message_hashes.clear()
            manager._active_task_id = None
            manager._initialized = True

            manager._active_task_id = data.get("active_task_id")
            manager._task_counter = data.get("task_counter", 0)

            # Restore tasks
            tasks_data = data.get("tasks", {})
            for tid, task_dict in tasks_data.items():
                # Convert status string back to enum if needed
                if isinstance(task_dict.get("status"), str):
                    task_dict["status"] = TaskStatus(task_dict["status"])
                # Convert cross_referenced_task_ids from list to set
                if isinstance(task_dict.get("cross_referenced_task_ids"), list):
                    task_dict["cross_referenced_task_ids"] = set(
                        task_dict["cross_referenced_task_ids"]
                    )
                # Handle datetime deserialization
                for date_field in ("created_at", "completed_at"):
                    val = task_dict.get(date_field)
                    if isinstance(val, str):
                        with contextlib.suppress(ValueError, TypeError):
                            task_dict[date_field] = datetime.fromisoformat(val)

                manager._tasks[tid] = TaskContext(**task_dict)

            # Restore message map
            msg_map = data.get("message_task_map", {})
            for str_idx, tid in msg_map.items():
                with contextlib.suppress(ValueError, TypeError):
                    manager._message_task_map[int(str_idx)] = tid

            # Restore tagged hashes
            hashes = data.get("tagged_message_hashes", [])
            manager._tagged_message_hashes = set(hashes)

        return manager
