"""Conversation-scoped compressed history storage.

Provides an in-memory store with TTL and max-size eviction.
Keyed by session_id for Muse (since Muse uses session IDs, not conversation IDs).
"""

import logging
import threading
import time

logger = logging.getLogger(__name__)


class CompressedHistoryStore:
    """Protocol for session-scoped compressed history storage."""

    def get(self, session_id: str) -> list | None:
        """Return stored compressed history for the session, or None."""
        ...

    def set(self, session_id: str, messages: list) -> None:
        """Store the final message list for the session."""
        ...

    def delete(self, session_id: str) -> None:
        """Remove stored history for the session."""
        ...


class InMemoryCompressedHistoryStore(CompressedHistoryStore):
    """In-memory store with TTL and max-size eviction.

    Key: session_id
    Value: tuple(list[ModelMessage], float) — messages + write timestamp
    Entries expire after TTL seconds.
    Oldest entries evicted when at capacity.
    """

    def __init__(self, ttl_seconds: int = 86400, max_sessions: int = 500):
        self._ttl = max(1, ttl_seconds)
        self._max = max(1, max_sessions)
        self._data: dict[str, tuple[list, float]] = {}
        self._lock = threading.Lock()

    def get(self, session_id: str) -> list | None:
        with self._lock:
            entry = self._data.get(session_id)
            if entry is None:
                return None
            messages, written_at = entry
            if time.monotonic() - written_at > self._ttl:
                del self._data[session_id]
                return None
            return list(messages)  # return a copy

    def set(self, session_id: str, messages: list) -> None:
        now = time.monotonic()
        with self._lock:
            if session_id in self._data:
                self._data[session_id] = (list(messages), now)
                return
            # Evict oldest if at capacity
            while len(self._data) >= self._max:
                oldest_key = min(self._data.keys(), key=lambda k: self._data[k][1])
                del self._data[oldest_key]
            self._data[session_id] = (list(messages), now)

    def delete(self, session_id: str) -> None:
        with self._lock:
            self._data.pop(session_id, None)

    def size(self) -> int:
        with self._lock:
            return len(self._data)


# Singleton
_store: InMemoryCompressedHistoryStore | None = None
_store_lock = threading.Lock()


def get_history_store() -> InMemoryCompressedHistoryStore:
    """Return the global compressed history store (lazy init)."""
    global _store
    with _store_lock:
        if _store is None:
            _store = InMemoryCompressedHistoryStore()
        return _store


def reset_history_store() -> None:
    """Reset the global store (for tests)."""
    global _store
    with _store_lock:
        _store = None
