"""Thread-safe in-memory blackboard store with scope isolation.

The store is the core of the blackboard plugin.  It provides:
- ``post``: add an artifact
- ``get``: retrieve an artifact by id within scope
- ``query``: list/filter artifacts by kind, tags, text, scope
- ``clear``: remove all artifacts in a scope
- ``stats``: artifact counts and estimated token savings

Scope isolation is mandatory: queries only return artifacts in the
exact requested scope.  ``global`` scope is a single shared namespace.
"""

import logging
import threading
from typing import Any

from code_muse.plugins.blackboard.models import (
    ArtifactKind,
    BlackboardArtifact,
    BlackboardScope,
    BlackboardScopeType,
)

logger = logging.getLogger(__name__)

# Rough token estimate: ~4 chars per token for English/code text.
_CHARS_PER_TOKEN = 4.0


class BlackboardStore:
    """Thread-safe in-memory store for blackboard artifacts.

    Artifacts are indexed by their scope key for O(1) scope-level
    lookups and by id for direct access.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # scope_key -> list of artifacts
        self._by_scope: dict[str, list[BlackboardArtifact]] = {}
        # artifact_id -> artifact (global index)
        self._by_id: dict[str, BlackboardArtifact] = {}

    # ------------------------------------------------------------------
    # Core operations
    # ------------------------------------------------------------------

    def post(self, artifact: BlackboardArtifact) -> BlackboardArtifact:
        """Add an artifact to the store. Returns the stored artifact."""
        with self._lock:
            scope_key = artifact.scope_key
            if scope_key not in self._by_scope:
                self._by_scope[scope_key] = []
            self._by_scope[scope_key].append(artifact)
            self._by_id[artifact.id] = artifact
        logger.debug(
            "Blackboard posted %s '%s' in scope %s",
            artifact.kind.value,
            artifact.id,
            scope_key,
        )
        return artifact

    def get(
        self,
        artifact_id: str,
        scope_type: BlackboardScopeType = BlackboardScopeType.session,
        scope_id: str = "default",
    ) -> BlackboardArtifact | None:
        """Retrieve an artifact by id if it belongs to the given scope."""
        scope = BlackboardScope(scope_type=scope_type, scope_id=scope_id)
        scope_key = scope.key
        with self._lock:
            artifact = self._by_id.get(artifact_id)
            if artifact is None:
                return None
            if artifact.scope_key != scope_key:
                return None
            return artifact

    def query(
        self,
        kind: ArtifactKind | None = None,
        tags: list[str] | None = None,
        text: str | None = None,
        scope_type: BlackboardScopeType = BlackboardScopeType.session,
        scope_id: str = "default",
        limit: int = 5,
    ) -> list[BlackboardArtifact]:
        """List artifacts matching filters within a specific scope.

        Scope isolation is enforced: only artifacts in the exact
        requested scope are returned.
        """
        scope = BlackboardScope(scope_type=scope_type, scope_id=scope_id)
        scope_key = scope.key
        with self._lock:
            candidates = list(self._by_scope.get(scope_key, []))

        results: list[BlackboardArtifact] = []
        for artifact in candidates:
            if kind is not None and artifact.kind != kind:
                continue
            if tags and not all(t in artifact.tags for t in tags):
                continue
            if text:
                text_lower = text.lower()
                if (
                    text_lower not in artifact.title.lower()
                    and text_lower not in artifact.content.lower()
                    and text_lower not in artifact.summary.lower()
                ):
                    continue
            results.append(artifact)

        # Return most recent first
        results.sort(key=lambda a: a.created_at, reverse=True)
        return results[:limit]

    def clear(
        self,
        scope_type: BlackboardScopeType = BlackboardScopeType.session,
        scope_id: str = "default",
    ) -> int:
        """Remove all artifacts in a scope. Returns count removed."""
        scope = BlackboardScope(scope_type=scope_type, scope_id=scope_id)
        scope_key = scope.key
        with self._lock:
            removed = self._by_scope.pop(scope_key, [])
            for artifact in removed:
                self._by_id.pop(artifact.id, None)
        count = len(removed)
        logger.debug(
            "Blackboard cleared scope %s: %d artifacts removed", scope_key, count
        )
        return count

    def delete(self, artifact_id: str) -> bool:
        """Remove a single artifact by id. Returns True if found and removed."""
        with self._lock:
            artifact = self._by_id.pop(artifact_id, None)
            if artifact is None:
                return False
            scope_key = artifact.scope_key
            if scope_key in self._by_scope:
                self._by_scope[scope_key] = [
                    a for a in self._by_scope[scope_key] if a.id != artifact_id
                ]
        return True

    # ------------------------------------------------------------------
    # Stats & token estimation
    # ------------------------------------------------------------------

    def stats(
        self,
        scope_type: BlackboardScopeType = BlackboardScopeType.session,
        scope_id: str = "default",
    ) -> dict[str, Any]:
        """Return stats for a scope including artifact count
        and token savings estimate."""
        scope = BlackboardScope(scope_type=scope_type, scope_id=scope_id)
        scope_key = scope.key
        with self._lock:
            artifacts = list(self._by_scope.get(scope_key, []))

        total_content_chars = sum(len(a.content) for a in artifacts)
        total_summary_chars = sum(len(a.summary) for a in artifacts if a.summary)

        # If summaries are used instead of full content, the chars saved:
        summary_or_content_chars = sum(
            len(a.summary) if a.summary else min(len(a.content), 200) for a in artifacts
        )
        saved_chars = max(0, total_content_chars - summary_or_content_chars)
        estimated_tokens_saved = int(saved_chars / _CHARS_PER_TOKEN)

        return {
            "scope_key": scope_key,
            "artifact_count": len(artifacts),
            "total_content_chars": total_content_chars,
            "total_summary_chars": total_summary_chars,
            "estimated_tokens_saved": estimated_tokens_saved,
            "by_kind": {
                kind.value: sum(1 for a in artifacts if a.kind == kind)
                for kind in ArtifactKind
            },
        }

    def all_scope_keys(self) -> list[str]:
        """Return all scope keys with artifacts (for status display)."""
        with self._lock:
            return list(self._by_scope.keys())

    def reset(self) -> None:
        """Clear all state. Used for testing and /blackboard reset."""
        with self._lock:
            self._by_scope.clear()
            self._by_id.clear()


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_store: BlackboardStore | None = None
_store_lock = threading.Lock()


def get_store() -> BlackboardStore:
    """Return the module-level BlackboardStore singleton."""
    global _store
    if _store is None:
        with _store_lock:
            if _store is None:
                _store = BlackboardStore()
    return _store


def reset_store() -> None:
    """Reset the singleton (for testing only)."""
    global _store
    with _store_lock:
        if _store is not None:
            _store.reset()
        _store = None
