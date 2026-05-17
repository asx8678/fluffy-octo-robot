"""Pydantic models for the Semantic Experience Store.

ExperienceCapsule: compact, retrievable record of a solved problem.
ExperienceSearchResult: ranked capsule with similarity score.
"""

from datetime import datetime
from uuid import uuid4

from pydantic import BaseModel, Field


class ExperienceCapsule(BaseModel):
    """Compact, retrievable record of a solved problem.

    Stored per-repo (or global if opted in) in a JSONL file.
    Designed for fast keyword + ngram-based retrieval without
    heavyweight embedding dependencies.
    """

    capsule_id: str = Field(
        default_factory=lambda: str(uuid4()),
        description="Unique identifier for this capsule",
    )
    task_id: str = Field(
        default="",
        description="Original task_id from task_context",
    )
    task_label: str = Field(
        default="",
        description="Human-readable task label",
    )
    outcome_summary: str = Field(
        default="",
        description="One-line summary of task outcome",
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(),
        description="When the original task was created",
    )
    completed_at: datetime | None = Field(
        default=None,
        description="When the task was completed",
    )
    repo_scope: str = Field(
        default="",
        description="Hash of the repo root (per-repo isolation)",
    )
    source_archive_path: str = Field(
        default="",
        description="Path to the original task archive JSON",
    )
    summary: str = Field(
        default="",
        description="Compact excerpt of the task's key solution steps",
    )
    key_terms: list[str] = Field(
        default_factory=list,
        description="Extracted keywords for fast matching",
    )
    structural_fingerprint: dict = Field(
        default_factory=dict,
        description="Tools used, file types, high-level steps",
    )
    semantic_signature: list[float] = Field(
        default_factory=list,
        description="Deterministic hash-vector for cosine similarity",
    )
    token_estimate: int = Field(
        default=0,
        ge=0,
        description="Estimated tokens the original task consumed",
    )
    metadata: dict = Field(
        default_factory=dict,
        description="Extra metadata (tag, category, etc.)",
    )

    model_config = {"extra": "allow"}


class ExperienceSearchResult(BaseModel):
    """A capsule ranked by similarity to a query."""

    capsule: ExperienceCapsule = Field(
        description="The matched experience capsule",
    )
    similarity: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Similarity score to the query (0.0–1.0)",
    )

    model_config = {"extra": "forbid"}
