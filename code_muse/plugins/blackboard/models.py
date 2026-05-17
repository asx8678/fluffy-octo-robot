"""Pydantic models for the Blackboard plugin.

Defines the typed data structures agents use to communicate:
- ``ArtifactKind``: enum of artifact categories
- ``BlackboardScope``: scope identifier (session, swarm, global)
- ``BlackboardArtifact``: the core artifact model
"""

import enum
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class ArtifactKind(enum.StrEnum):
    """Typed categories for blackboard artifacts."""

    design_doc = "design_doc"
    test_plan = "test_plan"
    bug_analysis = "bug_analysis"
    implementation_note = "implementation_note"
    review_verdict = "review_verdict"
    generic = "generic"


class BlackboardScopeType(enum.StrEnum):
    """Scope types controlling artifact visibility."""

    session = "session"
    swarm = "swarm"
    global_ = "global"


class BlackboardScope(BaseModel):
    """Identifies the visibility scope for artifacts.

    Scope isolation is mandatory: queries only return artifacts whose
    scope_type and scope_id match exactly (except ``global`` scope).
    """

    scope_type: BlackboardScopeType = Field(
        default=BlackboardScopeType.session,
        description="Visibility scope type",
    )
    scope_id: str = Field(
        default="default",
        description="Identifier within the scope type (session id, swarm id, etc.)",
    )

    @property
    def key(self) -> str:
        """Composite key used for scope isolation lookups."""
        if self.scope_type == BlackboardScopeType.global_:
            return "global"
        return f"{self.scope_type.value}:{self.scope_id}"


class BlackboardArtifact(BaseModel):
    """A typed artifact posted to the blackboard by an agent.

    Artifacts are the unit of inter-agent communication.  A planner posts
    a ``design_doc``; specialist agents query it by kind and scope rather
    than receiving the full reasoning in their prompt history.
    """

    id: str = Field(default_factory=lambda: uuid4().hex[:12])
    kind: ArtifactKind = Field(description="Artifact category")
    title: str = Field(description="Short human-readable title")
    content: str = Field(description="Full artifact content")
    summary: str = Field(
        default="", description="Compact summary for token-efficient queries"
    )
    tags: list[str] = Field(default_factory=list, description="Searchable tags")
    scope_type: BlackboardScopeType = Field(default=BlackboardScopeType.session)
    scope_id: str = Field(default="default")
    author_agent: str = Field(
        default="unknown", description="Agent that created the artifact"
    )
    session_id: str = Field(
        default="default", description="Session the artifact belongs to"
    )
    parent_artifact_id: str | None = Field(
        default=None,
        description="ID of the parent artifact for threading",
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
    )
    provenance: dict[str, Any] = Field(
        default_factory=dict,
        description="Extra metadata (depth, model, etc.)",
    )

    @property
    def scope_key(self) -> str:
        """Compute the scope key for this artifact."""
        scope = BlackboardScope(scope_type=self.scope_type, scope_id=self.scope_id)
        return scope.key

    def compact(self) -> dict[str, Any]:
        """Return a token-efficient representation for query results.

        Includes id, kind, title, summary (or truncated content), and tags.
        """
        display_summary = self.summary or self.content[:200]
        if len(display_summary) > 200:
            display_summary = display_summary[:197] + "..."
        return {
            "id": self.id,
            "kind": self.kind.value,
            "title": self.title,
            "summary": display_summary,
            "tags": self.tags,
            "author_agent": self.author_agent,
            "created_at": self.created_at.isoformat(),
        }


# ---------------------------------------------------------------------------
# Convenience constructors for common artifact types
# ---------------------------------------------------------------------------


def make_design_doc(
    title: str,
    content: str,
    summary: str = "",
    *,
    tags: list[str] | None = None,
    scope_type: BlackboardScopeType = BlackboardScopeType.session,
    scope_id: str = "default",
    author_agent: str = "unknown",
    session_id: str = "default",
    parent_artifact_id: str | None = None,
    provenance: dict[str, Any] | None = None,
) -> BlackboardArtifact:
    """Create a ``design_doc`` artifact."""
    return BlackboardArtifact(
        kind=ArtifactKind.design_doc,
        title=title,
        content=content,
        summary=summary,
        tags=tags or [],
        scope_type=scope_type,
        scope_id=scope_id,
        author_agent=author_agent,
        session_id=session_id,
        parent_artifact_id=parent_artifact_id,
        provenance=provenance or {},
    )


def make_test_plan(
    title: str,
    content: str,
    summary: str = "",
    *,
    tags: list[str] | None = None,
    scope_type: BlackboardScopeType = BlackboardScopeType.session,
    scope_id: str = "default",
    author_agent: str = "unknown",
    session_id: str = "default",
    parent_artifact_id: str | None = None,
    provenance: dict[str, Any] | None = None,
) -> BlackboardArtifact:
    """Create a ``test_plan`` artifact."""
    return BlackboardArtifact(
        kind=ArtifactKind.test_plan,
        title=title,
        content=content,
        summary=summary,
        tags=tags or [],
        scope_type=scope_type,
        scope_id=scope_id,
        author_agent=author_agent,
        session_id=session_id,
        parent_artifact_id=parent_artifact_id,
        provenance=provenance or {},
    )


def make_bug_analysis(
    title: str,
    content: str,
    summary: str = "",
    *,
    tags: list[str] | None = None,
    scope_type: BlackboardScopeType = BlackboardScopeType.session,
    scope_id: str = "default",
    author_agent: str = "unknown",
    session_id: str = "default",
    parent_artifact_id: str | None = None,
    provenance: dict[str, Any] | None = None,
) -> BlackboardArtifact:
    """Create a ``bug_analysis`` artifact."""
    return BlackboardArtifact(
        kind=ArtifactKind.bug_analysis,
        title=title,
        content=content,
        summary=summary,
        tags=tags or [],
        scope_type=scope_type,
        scope_id=scope_id,
        author_agent=author_agent,
        session_id=session_id,
        parent_artifact_id=parent_artifact_id,
        provenance=provenance or {},
    )
