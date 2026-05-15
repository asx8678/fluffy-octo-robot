"""Tests for task_context.models.

Pydantic model creation, defaults, validation, round-trip.
"""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from code_muse.plugins.task_context.models import (
    CompletionSignal,
    PruneAction,
    PruneDecision,
    PruneSummary,
    TaskContext,
    TaskMetadata,
    TaskShiftSignal,
    TaskStatus,
)

# ---------------------------------------------------------------------------
# TaskStatus enum
# ---------------------------------------------------------------------------


class TestTaskStatus:
    def test_values(self):
        assert TaskStatus.ACTIVE == "active"
        assert TaskStatus.COMPLETED == "completed"
        assert TaskStatus.ARCHIVED == "archived"

    def test_from_string(self):
        assert TaskStatus("active") is TaskStatus.ACTIVE
        assert TaskStatus("completed") is TaskStatus.COMPLETED

    def test_invalid_value_raises(self):
        with pytest.raises(ValueError):
            TaskStatus("pending")


# ---------------------------------------------------------------------------
# PruneAction enum
# ---------------------------------------------------------------------------


class TestPruneAction:
    def test_values(self):
        assert PruneAction.KEEP == "keep"
        assert PruneAction.ARCHIVE == "archive"
        assert PruneAction.DELETE == "delete"

    def test_from_string(self):
        assert PruneAction("archive") is PruneAction.ARCHIVE


# ---------------------------------------------------------------------------
# TaskMetadata
# ---------------------------------------------------------------------------


class TestTaskMetadata:
    def test_defaults(self):
        m = TaskMetadata()
        assert m.task_id  # non-empty UUID string
        assert m.task_status is TaskStatus.ACTIVE
        assert m.relevance_score == 1.0
        assert isinstance(m.last_accessed, datetime)
        assert m.message_index == 0

    def test_custom_values(self):
        now = datetime.now(tz=UTC)
        m = TaskMetadata(
            task_id="abc-123",
            task_status=TaskStatus.COMPLETED,
            relevance_score=0.5,
            last_accessed=now,
            message_index=42,
        )
        assert m.task_id == "abc-123"
        assert m.task_status is TaskStatus.COMPLETED
        assert m.relevance_score == 0.5
        assert m.last_accessed == now
        assert m.message_index == 42

    def test_relevance_score_bounds(self):
        with pytest.raises(ValidationError):
            TaskMetadata(relevance_score=-0.1)
        with pytest.raises(ValidationError):
            TaskMetadata(relevance_score=1.5)

    def test_message_index_must_be_non_negative(self):
        with pytest.raises(ValidationError):
            TaskMetadata(message_index=-1)

    def test_frozen_model_rejects_extra(self):
        with pytest.raises(ValidationError):
            TaskMetadata(extra_field="nope")

    def test_frozen_model_immutable(self):
        m = TaskMetadata()
        with pytest.raises(ValidationError):
            m.relevance_score = 0.3

    def test_serialization_round_trip(self):
        m = TaskMetadata(task_id="round-trip", relevance_score=0.75, message_index=5)
        data = m.model_dump(mode="json")
        m2 = TaskMetadata.model_validate(data)
        assert m2.task_id == m.task_id
        assert m2.relevance_score == m.relevance_score
        assert m2.message_index == m.message_index


# ---------------------------------------------------------------------------
# TaskContext
# ---------------------------------------------------------------------------


class TestTaskContext:
    def test_defaults(self):
        ctx = TaskContext()
        assert ctx.task_id
        assert ctx.label == ""
        assert ctx.status is TaskStatus.ACTIVE
        assert ctx.completed_at is None
        assert isinstance(ctx.last_accessed, datetime)
        assert ctx.auto_detected is False
        assert ctx.message_count == 0
        assert ctx.token_count == 0
        assert ctx.outcome_summary is None
        assert ctx.cross_referenced_task_ids == set()

    def test_custom_values(self):
        ctx = TaskContext(
            task_id="t1",
            label="refactor-auth",
            status=TaskStatus.COMPLETED,
            auto_detected=True,
            message_count=10,
            token_count=5000,
            outcome_summary="PR #42 merged",
            cross_referenced_task_ids={"t2", "t3"},
        )
        assert ctx.label == "refactor-auth"
        assert ctx.status is TaskStatus.COMPLETED
        assert ctx.auto_detected is True
        assert ctx.message_count == 10
        assert ctx.cross_referenced_task_ids == {"t2", "t3"}

    def test_mutable_fields(self):
        """TaskContext is NOT frozen — fields can be updated."""
        ctx = TaskContext()
        ctx.status = TaskStatus.COMPLETED
        ctx.message_count = 5
        ctx.token_count = 999
        assert ctx.status is TaskStatus.COMPLETED
        assert ctx.message_count == 5

    def test_message_count_must_be_non_negative(self):
        with pytest.raises(ValidationError):
            TaskContext(message_count=-1)

    def test_token_count_must_be_non_negative(self):
        with pytest.raises(ValidationError):
            TaskContext(token_count=-1)

    def test_extra_fields_rejected(self):
        with pytest.raises(ValidationError):
            TaskContext(bogus="nope")

    def test_serialization_round_trip(self):
        ctx = TaskContext(
            task_id="serialize-me",
            label="test-label",
            status=TaskStatus.COMPLETED,
            cross_referenced_task_ids={"x", "y"},
        )
        data = ctx.model_dump(mode="json")
        # Cross-refs become list in JSON
        assert isinstance(data["cross_referenced_task_ids"], list)

        ctx2 = TaskContext.model_validate(data)
        assert ctx2.task_id == ctx.task_id
        assert ctx2.label == ctx.label
        assert ctx2.status == ctx.status
        assert ctx2.cross_referenced_task_ids == {"x", "y"}


# ---------------------------------------------------------------------------
# TaskShiftSignal
# ---------------------------------------------------------------------------


class TestTaskShiftSignal:
    def test_defaults(self):
        sig = TaskShiftSignal()
        assert sig.detected is False
        assert sig.confidence == 0.0
        assert sig.signal_source == ""
        assert sig.suggested_label is None
        assert sig.trigger_message == ""

    def test_custom_values(self):
        sig = TaskShiftSignal(
            detected=True,
            confidence=0.85,
            signal_source="keyword",
            suggested_label="refactor-auth",
            trigger_message="Let's start a new task",
        )
        assert sig.detected is True
        assert sig.confidence == 0.85
        assert sig.signal_source == "keyword"

    def test_confidence_bounds(self):
        with pytest.raises(ValidationError):
            TaskShiftSignal(confidence=-0.01)
        with pytest.raises(ValidationError):
            TaskShiftSignal(confidence=1.01)

    def test_serialization_round_trip(self):
        sig = TaskShiftSignal(
            detected=True,
            confidence=0.65,
            signal_source="embedding",
            suggested_label="api-redesign",
        )
        data = sig.model_dump(mode="json")
        sig2 = TaskShiftSignal.model_validate(data)
        assert sig2.detected == sig.detected
        assert sig2.confidence == sig.confidence
        assert sig2.suggested_label == sig.suggested_label


# ---------------------------------------------------------------------------
# CompletionSignal
# ---------------------------------------------------------------------------


class TestCompletionSignal:
    def test_defaults(self):
        sig = CompletionSignal()
        assert sig.detected is False
        assert sig.confidence == 0.0
        assert sig.signal_source == ""
        assert sig.outcome_summary is None

    def test_custom_values(self):
        sig = CompletionSignal(
            detected=True,
            confidence=0.9,
            signal_source="explicit",
            outcome_summary="PR #10 merged",
        )
        assert sig.detected is True
        assert sig.confidence == 0.9
        assert sig.outcome_summary == "PR #10 merged"

    def test_confidence_bounds(self):
        with pytest.raises(ValidationError):
            CompletionSignal(confidence=2.0)

    def test_serialization_round_trip(self):
        sig = CompletionSignal(
            detected=True,
            confidence=0.5,
            signal_source="inactivity_timeout",
            outcome_summary="auto-completed (timeout)",
        )
        data = sig.model_dump(mode="json")
        sig2 = CompletionSignal.model_validate(data)
        assert sig2.outcome_summary == sig.outcome_summary


# ---------------------------------------------------------------------------
# PruneDecision
# ---------------------------------------------------------------------------


class TestPruneDecision:
    def test_required_fields(self):
        d = PruneDecision(message_index=3, action=PruneAction.KEEP)
        assert d.message_index == 3
        assert d.action is PruneAction.KEEP
        assert d.reason == ""
        assert d.task_id == ""
        assert d.relevance_score == 0.0

    def test_all_fields(self):
        d = PruneDecision(
            message_index=7,
            action=PruneAction.DELETE,
            reason="Low relevance from completed task",
            task_id="t1",
            relevance_score=0.15,
        )
        assert d.action is PruneAction.DELETE
        assert d.relevance_score == 0.15

    def test_message_index_must_be_non_negative(self):
        with pytest.raises(ValidationError):
            PruneDecision(message_index=-1, action=PruneAction.KEEP)

    def test_relevance_score_bounds(self):
        with pytest.raises(ValidationError):
            PruneDecision(
                message_index=0,
                action=PruneAction.KEEP,
                relevance_score=-0.1,
            )

    def test_serialization_round_trip(self):
        d = PruneDecision(
            message_index=2,
            action=PruneAction.ARCHIVE,
            reason="medium relevance",
            task_id="abc",
            relevance_score=0.45,
        )
        data = d.model_dump(mode="json")
        d2 = PruneDecision.model_validate(data)
        assert d2.message_index == d.message_index
        assert d2.action == d.action


# ---------------------------------------------------------------------------
# PruneSummary
# ---------------------------------------------------------------------------


class TestPruneSummary:
    def test_defaults(self):
        s = PruneSummary()
        assert s.total_messages_before == 0
        assert s.total_messages_after == 0
        assert s.tokens_before == 0
        assert s.tokens_after == 0
        assert s.tokens_saved == 0
        assert s.decisions == []
        assert s.archive_paths == {}

    def test_computed_properties(self):
        decisions = [
            PruneDecision(message_index=0, action=PruneAction.KEEP),
            PruneDecision(message_index=1, action=PruneAction.ARCHIVE),
            PruneDecision(message_index=2, action=PruneAction.DELETE),
            PruneDecision(message_index=3, action=PruneAction.KEEP),
            PruneDecision(message_index=4, action=PruneAction.ARCHIVE),
        ]
        s = PruneSummary(decisions=decisions)
        assert s.kept_count == 2
        assert s.archived_count == 2
        assert s.deleted_count == 1

    def test_empty_summary_counts(self):
        s = PruneSummary()
        assert s.kept_count == 0
        assert s.archived_count == 0
        assert s.deleted_count == 0

    def test_archive_paths(self):
        s = PruneSummary(
            archive_paths={"t1": "/path/to/t1.json", "t2": "/path/to/t2.json"},
        )
        assert len(s.archive_paths) == 2

    def test_serialization_round_trip(self):
        decisions = [
            PruneDecision(
                message_index=0,
                action=PruneAction.DELETE,
                reason="test",
                task_id="t1",
                relevance_score=0.1,
            ),
        ]
        s = PruneSummary(
            total_messages_before=10,
            total_messages_after=9,
            tokens_before=1000,
            tokens_after=900,
            tokens_saved=100,
            decisions=decisions,
            archive_paths={"t1": "/tmp/t1.json"},
        )
        data = s.model_dump(mode="json")
        s2 = PruneSummary.model_validate(data)
        assert s2.total_messages_before == 10
        assert s2.kept_count == s.kept_count
        assert s2.archive_paths == s.archive_paths
