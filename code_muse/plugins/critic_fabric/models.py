"""Canonical data models for the Critic Fabric.

These models are the *single source of truth* for all critic consumers
in Muse.  Every plugin that performs code review should produce or
consume ``CriticVerdict`` instances (or convert to/from them via
``to_dict()`` for backward compatibility).

Why Pydantic?
-------------

Pydantic gives us:
- declarative validation and defaults
- cheap serialisation (``model_dump()`` / ``model_dump_json()``)
- IDE auto-complete on every field
- forward-compatible if we ever want to ship verdicts over the wire
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class VerdictKind(StrEnum):
    """Possible verdict outcomes from a critic review."""

    APPROVED = "approved"
    REJECTED = "rejected"
    FLAGGED = "flagged"
    ERROR = "error"
    NEEDS_CHANGES = "needs_changes"


class CriticIssue(BaseModel):
    """A single issue identified during review."""

    severity: str = Field(
        "warning",
        description="Severity level: 'critical', 'warning', or 'info'",
    )
    message: str = Field(..., description="Human-readable description")
    suggestion: str | None = Field(
        None,
        description="Optional suggestion for resolution",
    )


class CriticLocation(BaseModel):
    """A specific location in a file referenced by a review finding."""

    file_path: str = Field("", description="Path to the file")
    start_line: int | None = Field(None, description="Start line (1-based)")
    end_line: int | None = Field(None, description="End line (1-based, inclusive)")
    description: str = Field("", description="What was found at this location")


class ReasonCode(BaseModel):
    """Machine-readable reason code with human explanation."""

    code: str = Field(
        "",
        description="Machine-readable key like 'SEC-001', 'STYLE-003'",
    )
    text: str = Field("", description="Human-readable explanation")


class CriticRequest(BaseModel):
    """A review request submitted to the critic fabric.

    All fields are intentionally kept flat — nested metadata goes in
    ``metadata`` so that callers don't need to construct deep trees.
    """

    file_path: str = Field(..., description="Path to the file under review")
    code_snippet: str = Field(
        ...,
        description="The code content to review",
    )
    operation: str = Field(
        "review",
        description="Operation that triggered the review",
    )
    agent_name: str = Field(
        "unknown",
        description="Name of the agent that produced the code",
    )
    backend: str = Field(
        "code_critic",
        description="Requested backend name (e.g. 'light', 'heavy', 'debate')",
    )
    metadata: dict = Field(
        default_factory=dict,
        description="Optional extra context for the backend",
    )


class CriticVerdict(BaseModel):
    """Structured verdict returned by every critic backend.

    Every field has a sensible default so that quick-reject from preflight
    can construct a verdict with minimal boilerplate.
    """

    verdict: VerdictKind = Field(..., description="The review outcome")
    summary: str = Field("", description="One-sentence summary of the reasoning")
    issues: list[str] = Field(
        default_factory=list,
        description="Human-readable issue descriptions",
    )
    suggestion: str | None = Field(
        None,
        description="Suggested action when verdict is not 'approved'",
    )
    raw_response: str | None = Field(
        None,
        description="Raw LLM response text (for debugging / provenance)",
    )
    backend: str = Field(
        "",
        description="Name of the backend that produced this verdict",
    )
    preflight_rejected: bool = Field(
        False,
        description="True if preflight checks rejected before backend ran",
    )
    reasons: list[ReasonCode] = Field(
        default_factory=list,
        description="Machine-readable reason codes",
    )
    locations: list[CriticLocation] = Field(
        default_factory=list,
        description="Specific file/line locations",
    )
    confidence: float = Field(
        0.0,
        ge=0.0,
        le=1.0,
        description="Reviewer confidence in the verdict (0–1)",
    )
    reviewer_id: str = Field("", description="Identifier of the reviewer")
    review_hash: str = Field(
        "",
        description="Deterministic: SHA256(content_hash::reviewer_id)[:16]",
    )
    content_hash: str = Field(
        "",
        description="Deterministic: SHA256(file_path::code_snippet)[:16]",
    )

    # ------------------------------------------------------------------
    # Compatibility helpers
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        """Convert to the legacy dict shape used by ``code_critic.reviewer``.

        The dict always contains the keys ``verdict``, ``summary``,
        ``issues``, and ``suggestion`` — matching the shape that
        existing consumers expect.  New fields are included as
        optional extras only when they have non-default values.
        """
        d: dict = {
            "verdict": self.verdict.value,
            "summary": self.summary,
            "issues": list(self.issues),
            "suggestion": self.suggestion,
        }
        if self.raw_response is not None:
            d["raw_response"] = self.raw_response
        # New structured fields — included only when populated
        if self.review_hash:
            d["review_hash"] = self.review_hash
        if self.content_hash:
            d["content_hash"] = self.content_hash
        if self.confidence > 0.0:
            d["confidence"] = self.confidence
        if self.reviewer_id:
            d["reviewer_id"] = self.reviewer_id
        if self.reasons:
            d["reasons"] = [r.model_dump() for r in self.reasons]
        if self.locations:
            d["locations"] = [loc.model_dump() for loc in self.locations]
        return d

    @classmethod
    def from_dict(
        cls,
        data: dict,
        *,
        backend: str = "",
        preflight_rejected: bool = False,
    ) -> CriticVerdict:
        """Construct from the legacy dict shape.

        Tolerates missing keys so that dicts produced by older
        ``code_critic.reviewer.review_code()`` calls are accepted.
        Also parses new structured fields when present.
        """
        raw_verdict = data.get("verdict", "flagged")
        try:
            kind = VerdictKind(raw_verdict)
        except ValueError:
            kind = VerdictKind.FLAGGED

        # Parse new optional fields — tolerate absence
        reasons_data = data.get("reasons", [])
        reasons = [ReasonCode(**r) if isinstance(r, dict) else r for r in reasons_data]

        locations_data = data.get("locations", [])
        locations = [
            CriticLocation(**loc) if isinstance(loc, dict) else loc
            for loc in locations_data
        ]

        return cls(
            verdict=kind,
            summary=data.get("summary", ""),
            issues=list(data.get("issues", [])),
            suggestion=data.get("suggestion"),
            raw_response=data.get("raw_response"),
            backend=backend,
            preflight_rejected=preflight_rejected,
            reasons=reasons,
            locations=locations,
            confidence=data.get("confidence", 0.0),
            reviewer_id=data.get("reviewer_id", ""),
            review_hash=data.get("review_hash", ""),
            content_hash=data.get("content_hash", ""),
        )
