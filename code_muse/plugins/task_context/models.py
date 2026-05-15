"""Pydantic models for task-aware context management.

TaskMetadata: lightweight tag attached to each message/chunk
TaskContext: full context for a task (registry entry)
TaskShiftSignal: result from auto-detection
CompletionSignal: result from completion detection
PruneDecision: action to take on a message during pruning
"""

from datetime import datetime
from enum import StrEnum
from uuid import uuid4

from pydantic import BaseModel, Field


class TaskStatus(StrEnum):
    """Lifecycle status of a task."""

    ACTIVE = "active"
    COMPLETED = "completed"
    ARCHIVED = "archived"


class PruneAction(StrEnum):
    """Action to take on a message during pruning."""

    KEEP = "keep"
    ARCHIVE = "archive"
    DELETE = "delete"


class TaskMetadata(BaseModel):
    """Lightweight metadata tag attached to each message/chunk.

    Stored alongside each message in the history for quick filtering.
    """

    task_id: str = Field(
        default_factory=lambda: str(uuid4()),
        description="Unique identifier for the originating task",
    )
    task_status: TaskStatus = Field(
        default=TaskStatus.ACTIVE,
        description="Current lifecycle status of the originating task",
    )
    relevance_score: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Relevance to the current active task (0.0–1.0)",
    )
    last_accessed: datetime = Field(
        default_factory=lambda: datetime.now(),
        description="When this message was last referenced",
    )
    message_index: int = Field(
        default=0,
        ge=0,
        description="Index of this message within the task's message sequence",
    )

    model_config = {"frozen": True, "extra": "forbid"}


class TaskContext(BaseModel):
    """Full registry entry for a task in the current session.

    Tracks all metadata associated with a task across its lifecycle.
    """

    task_id: str = Field(
        default_factory=lambda: str(uuid4()),
        description="Unique identifier for this task",
    )
    label: str = Field(
        default="",
        description="Human-readable label (user-provided or auto-detected)",
    )
    status: TaskStatus = Field(
        default=TaskStatus.ACTIVE,
        description="Current lifecycle status",
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(),
        description="When this task was created",
    )
    completed_at: datetime | None = Field(
        default=None,
        description="When this task was marked complete",
    )
    auto_detected: bool = Field(
        default=False,
        description="Whether this task was auto-detected vs user-created",
    )
    message_count: int = Field(
        default=0,
        ge=0,
        description="Number of messages tagged with this task_id",
    )
    token_count: int = Field(
        default=0,
        ge=0,
        description="Estimated total tokens for this task's messages",
    )
    outcome_summary: str | None = Field(
        default=None,
        description="Optional one-line summary of task outcome (for later recall)",
    )
    cross_referenced_task_ids: set[str] = Field(
        default_factory=set,
        description="Task_ids that share cross-referenced messages with this task",
    )

    model_config = {"frozen": False, "extra": "forbid"}


class TaskShiftSignal(BaseModel):
    """Result from auto-detection of a task shift."""

    detected: bool = Field(
        default=False,
        description="Whether a task shift was detected",
    )
    confidence: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Confidence score of the detection (0.0–1.0)",
    )
    signal_source: str = Field(
        default="",
        description="Source of the signal: 'keyword', 'embedding', 'explicit'",
    )
    suggested_label: str | None = Field(
        default=None,
        description="Suggested label for the new task, if extractable",
    )
    trigger_message: str = Field(
        default="",
        description="The message that triggered the detection",
    )


class CompletionSignal(BaseModel):
    """Result from detection of task completion."""

    detected: bool = Field(
        default=False,
        description="Whether task completion was detected",
    )
    confidence: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Confidence score (0.0–1.0)",
    )
    signal_source: str = Field(
        default="",
        description="Source: 'explicit', 'agent_self_assessment', 'inactivity_timeout'",
    )
    outcome_summary: str | None = Field(
        default=None,
        description="Extracted outcome summary if available",
    )


class PruneDecision(BaseModel):
    """Decision for a single message during pruning evaluation."""

    message_index: int = Field(
        ...,
        ge=0,
        description="Index of the message in the history list",
    )
    action: PruneAction = Field(
        ...,
        description="What to do with this message",
    )
    reason: str = Field(
        default="",
        description="Human-readable reason for the decision",
    )
    task_id: str = Field(
        default="",
        description="Task_id of the originating task",
    )
    relevance_score: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Computed relevance score that drove the decision",
    )


class PruneSummary(BaseModel):
    """Summary of a pruning pass for observability."""

    total_messages_before: int = Field(default=0)
    total_messages_after: int = Field(default=0)
    tokens_before: int = Field(default=0)
    tokens_after: int = Field(default=0)
    tokens_saved: int = Field(default=0)
    decisions: list[PruneDecision] = Field(default_factory=list)
    archive_paths: dict[str, str] = Field(
        default_factory=dict,
        description="task_id → archive file path for archived tasks",
    )

    @property
    def kept_count(self) -> int:
        return sum(1 for d in self.decisions if d.action == PruneAction.KEEP)

    @property
    def archived_count(self) -> int:
        return sum(1 for d in self.decisions if d.action == PruneAction.ARCHIVE)

    @property
    def deleted_count(self) -> int:
        return sum(1 for d in self.decisions if d.action == PruneAction.DELETE)
