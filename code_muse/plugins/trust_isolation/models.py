"""Core models for the Trust & Isolation plugin.

Defines the data structures for scoping, provenance, and capabilities
that the blackboard and experience store will use.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Scope
# ---------------------------------------------------------------------------


def _default_scope() -> str:
    """Derive a scope from the current git repo root, or fall back to 'global'.

    The scope is a stable identifier for the workspace. We hash the repo
    root path so that different clones of the same repo share a scope,
    while unrelated projects are isolated.

    Returns:
        A scope string like ``repo:<sha256hash>`` or ``global``.
    """
    import hashlib
    import subprocess
    from pathlib import Path

    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            repo_root = result.stdout.strip()
            digest = hashlib.sha256(repo_root.encode()).hexdigest()[:16]
            return f"repo:{digest}"
    except OSError, subprocess.TimeoutExpired:
        pass

    # Fallback: hash the CWD
    cwd = str(Path.cwd())
    digest = hashlib.sha256(cwd.encode()).hexdigest()[:16]
    return f"workspace:{digest}"


class Scope(BaseModel):
    """An isolation boundary for artifacts and capsules.

    Scopes are hierarchical: ``repo:abc`` is a parent of
    ``repo:abc:swarm:xyz``. By default, artifacts are only visible
    within their own scope or child scopes.
    """

    scope_id: str = Field(
        default_factory=_default_scope,
        description="Scope identifier (e.g. ``repo:abc123`` or ``global``)",
    )
    parent_scope: str | None = Field(
        default=None,
        description="Parent scope for hierarchical lookups",
    )

    model_config = {"frozen": True, "extra": "forbid"}

    def is_ancestor_of(self, other: Scope) -> bool:
        """Return True if this scope is an ancestor of *other*."""
        if other.parent_scope is None:
            return False
        if other.parent_scope == self.scope_id:
            return True
        # Walk up the hierarchy (max 8 levels to prevent cycles)
        current = other
        for _ in range(8):
            if current.parent_scope is None:
                return False
            return current.parent_scope == self.scope_id
        return False

    def contains(self, other: Scope) -> bool:
        """Return True if *other* is within this scope's boundary."""
        return other.scope_id == self.scope_id or self.is_ancestor_of(other)


# ---------------------------------------------------------------------------
# Provenance
# ---------------------------------------------------------------------------


class Provenance(BaseModel):
    """Who created an artifact and when.

    Every artifact on the blackboard and every capsule in the experience
    store carries a ``Provenance`` tag. This enables:
    - Audit trails (who posted what)
    - Poisoning detection (low-confidence or unknown agents)
    - Scope attribution (which task/project produced this)
    """

    agent_name: str = Field(
        description="Name of the agent that created this artifact",
    )
    task_id: str | None = Field(
        default=None,
        description="Task ID under which this was created",
    )
    session_id: str | None = Field(
        default=None,
        description="Sub-agent session that produced this",
    )
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(),
        description="When this artifact was created",
    )
    confidence: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Confidence score of the producing agent",
    )
    scope: Scope = Field(
        default_factory=Scope,
        description="Scope boundary for this artifact",
    )

    model_config = {"frozen": True, "extra": "forbid"}


# ---------------------------------------------------------------------------
# Capabilities
# ---------------------------------------------------------------------------


class Capability(StrEnum):
    """Declares what a tool can do with the blackboard / experience store.

    Tools must declare their required capability. The scope engine
    checks that the caller's scope + capability match the target
    artifact's scope + policy.
    """

    BLACKBOARD_READ = "blackboard:read"
    BLACKBOARD_WRITE = "blackboard:write"
    BLACKBOARD_ADMIN = "blackboard:admin"  # cross-scope, TTL mgmt
    EXPERIENCE_READ = "experience:read"
    EXPERIENCE_WRITE = "experience:write"
    EXPERIENCE_ADMIN = "experience:admin"  # purge, export, scoring override


class CapabilityPolicy(BaseModel):
    """Policy entry: which agent/capability combos are allowed.

    Default policy: same-scope reads always allowed; same-scope writes
    allowed; cross-scope requires explicit entry.
    """

    agent_pattern: str = Field(
        default="*",
        description="fnmatch pattern for agent names (``*`` = all)",
    )
    capability: Capability = Field(
        description="The capability this entry governs",
    )
    scope_pattern: str = Field(
        default="self",
        description="``self`` = caller's own scope, ``*`` = any scope, "
        "or a specific scope ID",
    )
    allowed: bool = Field(
        default=True,
        description="Whether this combination is allowed",
    )

    model_config = {"frozen": True, "extra": "forbid"}


# ---------------------------------------------------------------------------
# Artifact (generic blackboard entry)
# ---------------------------------------------------------------------------


class ArtifactType(StrEnum):
    """Well-known artifact types for the blackboard."""

    DESIGN_DOC = "design_doc"
    BUG_REPORT = "bug_report"
    PARTIAL_SOLUTION = "partial_solution"
    TEST_PLAN = "test_plan"
    REVIEW_RESULT = "review_result"
    NOTE = "note"
    CUSTOM = "custom"


class Artifact(BaseModel):
    """A single entry on the structured blackboard.

    Artifacts are typed, scoped, provenance-tagged pieces of data that
    agents can post and query. They form the foundation of inter-agent
    coordination.
    """

    artifact_id: str = Field(
        default_factory=lambda: str(uuid4()),
        description="Unique identifier",
    )
    artifact_type: ArtifactType | str = Field(
        default=ArtifactType.NOTE,
        description="Type of this artifact",
    )
    scope: Scope = Field(
        default_factory=Scope,
        description="Isolation boundary",
    )
    provenance: Provenance = Field(
        description="Who created this artifact",
    )
    title: str = Field(
        default="",
        description="Short human-readable title",
    )
    content: Any = Field(
        default=None,
        description="Payload — can be string, dict, or structured model",
    )
    ttl_seconds: int | None = Field(
        default=None,
        description="Time-to-live in seconds; None = no expiry",
    )
    tags: set[str] = Field(
        default_factory=set,
        description="Free-form tags for querying",
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(),
    )

    model_config = {"extra": "forbid"}


# ---------------------------------------------------------------------------
# Experience Capsule
# ---------------------------------------------------------------------------


class ExperienceCapsule(BaseModel):
    """A distilled outcome from a completed task.

    Stored in the experience store for semantic retrieval. Carries
    provenance for poisoning resistance and scope for privacy.
    """

    capsule_id: str = Field(
        default_factory=lambda: str(uuid4()),
        description="Unique identifier",
    )
    scope: Scope = Field(
        default_factory=Scope,
        description="Repo/workspace boundary — cross-scope retrieval opt-in",
    )
    provenance: Provenance = Field(
        description="Who produced this solution and when",
    )
    problem_signature: str = Field(
        default="",
        description="Hash/embedding fingerprint of the problem",
    )
    outcome_summary: str = Field(
        description="One-line distilled result",
    )
    approach: str = Field(
        default="",
        description="How the problem was solved (for learning)",
    )
    token_cost: int = Field(
        default=0,
        ge=0,
        description="Approximate tokens consumed",
    )
    confidence: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Quality confidence from the producing agent",
    )
    artifacts: list[str] = Field(
        default_factory=list,
        description="Linked artifact IDs from the blackboard",
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(),
    )

    model_config = {"extra": "forbid"}
