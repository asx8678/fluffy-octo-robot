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

    # ------------------------------------------------------------------
    # Compatibility helpers
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        """Convert to the legacy dict shape used by ``code_critic.reviewer``.

        The dict always contains the keys ``verdict``, ``summary``,
        ``issues``, and ``suggestion`` — matching the shape that
        existing consumers expect.
        """
        d: dict = {
            "verdict": self.verdict.value,
            "summary": self.summary,
            "issues": list(self.issues),
            "suggestion": self.suggestion,
        }
        if self.raw_response is not None:
            d["raw_response"] = self.raw_response
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
        """
        raw_verdict = data.get("verdict", "flagged")
        try:
            kind = VerdictKind(raw_verdict)
        except ValueError:
            kind = VerdictKind.FLAGGED

        return cls(
            verdict=kind,
            summary=data.get("summary", ""),
            issues=list(data.get("issues", [])),
            suggestion=data.get("suggestion"),
            raw_response=data.get("raw_response"),
            backend=backend,
            preflight_rejected=preflight_rejected,
        )
