"""Tests for debate plugin Pydantic schemas.

Validates model construction, validation rules, serialization,
and enum behaviour for VerdictKind, Issue, Verdict, ReviewRequest,
and ReviewResponse.
"""

import pytest
from pydantic import ValidationError

from code_muse.plugins.debate.schemas import (
    Issue,
    ReviewRequest,
    ReviewResponse,
    Verdict,
    VerdictKind,
)

# ---------------------------------------------------------------------------
# VerdictKind enum
# ---------------------------------------------------------------------------


class TestVerdictKind:
    """VerdictKind StrEnum behaviour and value tests."""

    def test_enum_values(self):
        assert VerdictKind.APPROVE == "approve"
        assert VerdictKind.REVISE == "revise"
        assert VerdictKind.REJECT == "reject"

    def test_enum_from_value(self):
        assert VerdictKind("approve") == VerdictKind.APPROVE
        assert VerdictKind("revise") == VerdictKind.REVISE
        assert VerdictKind("reject") == VerdictKind.REJECT

    def test_enum_invalid_value_raises(self):
        with pytest.raises(ValueError):
            VerdictKind("maybe")

    def test_enum_is_str(self):
        """VerdictKind values should be usable as plain strings."""
        assert isinstance(VerdictKind.APPROVE, str)
        assert VerdictKind.APPROVE + "!" == "approve!"

    def test_enum_members(self):
        assert len(VerdictKind) == 3


# ---------------------------------------------------------------------------
# Issue model
# ---------------------------------------------------------------------------


class TestIssue:
    """Issue model construction and validation."""

    def test_required_fields(self):
        issue = Issue(severity="critical", message="SQL injection")
        assert issue.severity == "critical"
        assert issue.message == "SQL injection"
        assert issue.suggestion is None

    def test_optional_suggestion(self):
        issue = Issue(
            severity="warning",
            message="Missing docs",
            suggestion="Add docstrings",
        )
        assert issue.suggestion == "Add docstrings"

    def test_missing_required_field(self):
        with pytest.raises(ValidationError):
            Issue(severity="info")

    def test_serialization_roundtrip(self):
        issue = Issue(severity="critical", message="XSS", suggestion="Escape output")
        data = issue.model_dump()
        restored = Issue.model_validate(data)
        assert restored == issue


# ---------------------------------------------------------------------------
# Verdict model
# ---------------------------------------------------------------------------


class TestVerdict:
    """Verdict model construction, validation, and serialisation."""

    def test_approve_verdict(self):
        v = Verdict(kind=VerdictKind.APPROVE, summary="Looks good")
        assert v.kind == VerdictKind.APPROVE
        assert v.summary == "Looks good"
        assert v.issues == []
        assert v.confidence == 0.0

    def test_revise_with_issues(self):
        issues = [
            Issue(severity="critical", message="Bug"),
            Issue(severity="warning", message="Style"),
        ]
        v = Verdict(
            kind=VerdictKind.REVISE,
            summary="Needs work",
            issues=issues,
            confidence=0.75,
        )
        assert len(v.issues) == 2
        assert v.confidence == 0.75

    def test_confidence_clamped_below_zero(self):
        with pytest.raises(ValidationError):
            Verdict(kind=VerdictKind.APPROVE, summary="X", confidence=-0.1)

    def test_confidence_clamped_above_one(self):
        with pytest.raises(ValidationError):
            Verdict(kind=VerdictKind.APPROVE, summary="X", confidence=1.5)

    def test_confidence_boundary_zero(self):
        v = Verdict(kind=VerdictKind.APPROVE, summary="X", confidence=0.0)
        assert v.confidence == 0.0

    def test_confidence_boundary_one(self):
        v = Verdict(kind=VerdictKind.APPROVE, summary="X", confidence=1.0)
        assert v.confidence == 1.0

    def test_missing_kind_raises(self):
        with pytest.raises(ValidationError):
            Verdict(summary="No kind")

    def test_missing_summary_raises(self):
        with pytest.raises(ValidationError):
            Verdict(kind=VerdictKind.APPROVE)

    def test_serialization_roundtrip(self):
        v = Verdict(
            kind=VerdictKind.REVISE,
            summary="Fix it",
            issues=[Issue(severity="warning", message="Bad")],
            confidence=0.6,
        )
        data = v.model_dump()
        restored = Verdict.model_validate(data)
        assert restored.kind == v.kind
        assert restored.summary == v.summary
        assert len(restored.issues) == 1
        assert restored.confidence == v.confidence

    def test_json_serialization(self):
        v = Verdict(kind=VerdictKind.APPROVE, summary="OK", confidence=0.9)
        json_str = v.model_dump_json()
        restored = Verdict.model_validate_json(json_str)
        assert restored == v


# ---------------------------------------------------------------------------
# ReviewRequest model
# ---------------------------------------------------------------------------


class TestReviewRequest:
    """ReviewRequest construction and checkpoint validation."""

    def test_valid_request(self):
        req = ReviewRequest(proposal="Refactor auth", checkpoint=1)
        assert req.proposal == "Refactor auth"
        assert req.checkpoint == 1
        assert req.reasoning_summary == ""

    def test_request_with_reasoning(self):
        req = ReviewRequest(
            proposal="Refactor auth",
            reasoning_summary="Security concern",
            checkpoint=5,
        )
        assert req.reasoning_summary == "Security concern"
        assert req.checkpoint == 5

    def test_checkpoint_zero_raises(self):
        with pytest.raises(ValidationError):
            ReviewRequest(proposal="X", checkpoint=0)

    def test_checkpoint_negative_raises(self):
        with pytest.raises(ValidationError):
            ReviewRequest(proposal="X", checkpoint=-1)

    def test_missing_proposal_raises(self):
        with pytest.raises(ValidationError):
            ReviewRequest(checkpoint=1)

    def test_missing_checkpoint_raises(self):
        with pytest.raises(ValidationError):
            ReviewRequest(proposal="X")

    def test_serialization_roundtrip(self):
        req = ReviewRequest(proposal="Test", reasoning_summary="Reason", checkpoint=3)
        data = req.model_dump()
        restored = ReviewRequest.model_validate(data)
        assert restored == req


# ---------------------------------------------------------------------------
# ReviewResponse model
# ---------------------------------------------------------------------------


class TestReviewResponse:
    """ReviewResponse construction and field validation."""

    def test_valid_response(self):
        resp = ReviewResponse(
            verdict=Verdict(kind=VerdictKind.APPROVE, summary="OK"),
            review_count=1,
            remaining_budget=19,
        )
        assert resp.verdict.kind == VerdictKind.APPROVE
        assert resp.review_count == 1
        assert resp.remaining_budget == 19

    def test_missing_verdict_raises(self):
        with pytest.raises(ValidationError):
            ReviewResponse(review_count=1, remaining_budget=19)

    def test_missing_review_count_raises(self):
        with pytest.raises(ValidationError):
            ReviewResponse(
                verdict=Verdict(kind=VerdictKind.APPROVE, summary="OK"),
                remaining_budget=19,
            )

    def test_serialization_roundtrip(self):
        resp = ReviewResponse(
            verdict=Verdict(
                kind=VerdictKind.REVISE,
                summary="Fix",
                issues=[Issue(severity="critical", message="Bug")],
                confidence=0.8,
            ),
            review_count=5,
            remaining_budget=15,
        )
        data = resp.model_dump()
        restored = ReviewResponse.model_validate(data)
        assert restored.verdict.kind == VerdictKind.REVISE
        assert restored.review_count == 5
        assert len(restored.verdict.issues) == 1

    def test_zero_remaining_budget(self):
        resp = ReviewResponse(
            verdict=Verdict(kind=VerdictKind.APPROVE, summary="OK"),
            review_count=20,
            remaining_budget=0,
        )
        assert resp.remaining_budget == 0
