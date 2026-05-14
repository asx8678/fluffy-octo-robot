"""Pydantic schemas for the Debate Mode plugin.

Defines the structured data exchanged between the planner and reviewer:
- ``Verdict`` — the reviewer's decision on a proposal
- ``ReviewRequest`` — what the planner submits for review
- ``ReviewResponse`` — the full result returned to the planner
"""

from enum import StrEnum

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Verdicts
# ---------------------------------------------------------------------------


class VerdictKind(StrEnum):
    """Possible verdicts from the reviewer."""

    APPROVE = "approve"
    REVISE = "revise"
    REJECT = "reject"


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class Issue(BaseModel):
    """A single issue identified by the reviewer."""

    severity: str = Field(
        ...,
        description="Severity level: 'critical', 'warning', or 'info'",
    )
    message: str = Field(..., description="Human-readable description of the issue")
    suggestion: str | None = Field(
        None, description="Optional suggestion for resolution"
    )


class Verdict(BaseModel):
    """The reviewer's structured verdict on a proposal."""

    kind: VerdictKind = Field(
        ..., description="The decision: approve, revise, or reject"
    )
    summary: str = Field(..., description="One-sentence summary of the reasoning")
    issues: list[Issue] = Field(
        default_factory=list, description="Issues found during review"
    )
    confidence: float = Field(
        0.0,
        ge=0.0,
        le=1.0,
        description="Reviewer confidence in the verdict (0–1)",
    )


class ReviewRequest(BaseModel):
    """A proposal submitted by the planner for review."""

    proposal: str = Field(..., description="The planner's current proposal text")
    reasoning_summary: str = Field(
        default="",
        description="Brief summary of the reasoning leading to this proposal",
    )
    checkpoint: int = Field(
        ...,
        ge=1,
        description="Monotonically increasing checkpoint number",
    )


class ReviewResponse(BaseModel):
    """The full response returned to the planner after a review."""

    verdict: Verdict
    review_count: int = Field(
        ..., description="Total reviews performed in this session so far"
    )
    remaining_budget: int = Field(
        ..., description="How many more reviews are allowed this session"
    )
