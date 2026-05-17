"""Blackboard plugin — structured, typed, scoped inter-agent communication.

Provides a shared blackboard where agents can post and query typed
``BlackboardArtifact`` objects within isolated scopes (session or swarm).
This replaces implicit "pass everything in prompt + full history"
communication with explicit, typed, scoped artifacts that collaborating
agents read on-demand.

Components:
    - models: Pydantic data models (ArtifactKind, BlackboardScope, BlackboardArtifact)
    - store: Thread-safe in-memory artifact store with scope isolation
    - config: Runtime configuration (durable on/off, data paths)
    - durable: Optional JSONL persistence backend
    - register_callbacks: Plugin hook wiring (tools, commands, prompts)
"""

from code_muse.plugins.blackboard.models import (
    ArtifactKind,
    BlackboardArtifact,
    BlackboardScope,
    BlackboardScopeType,
)
from code_muse.plugins.blackboard.store import BlackboardStore, get_store

__all__ = [
    "ArtifactKind",
    "BlackboardArtifact",
    "BlackboardScope",
    "BlackboardScopeType",
    "BlackboardStore",
    "get_store",
]
