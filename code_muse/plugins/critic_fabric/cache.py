"""Review cache with content-hash deduplication for critic_fabric.

Thread-safe in-memory cache keyed by content_hash + reviewer_id so that
identical review requests are served from cache instead of invoking the
backend a second time.
"""

from __future__ import annotations

import hashlib
import threading
from dataclasses import dataclass
from typing import Any


@dataclass
class CacheStats:
    """Simple hit/miss/size counters."""

    hits: int = 0
    misses: int = 0
    size: int = 0


class CriticReviewCache:
    """Thread-safe in-memory review cache keyed by content_hash + reviewer.

    Key format: ``SHA256(content_hash::reviewer_id)[:32]``
    """

    def __init__(self) -> None:
        self._cache: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._stats = CacheStats()

    def _key(self, content_hash: str, reviewer_id: str = "") -> str:
        raw = f"{content_hash}::{reviewer_id}"
        return hashlib.sha256(raw.encode()).hexdigest()[:32]

    def get(self, content_hash: str, reviewer_id: str = "") -> dict | None:
        """Return cached verdict dict or ``None`` on miss."""
        with self._lock:
            k = self._key(content_hash, reviewer_id)
            if k in self._cache:
                self._stats.hits += 1
                return self._cache[k]
            self._stats.misses += 1
            return None

    def set(
        self,
        content_hash: str,
        verdict_dict: dict,
        reviewer_id: str = "",
    ) -> None:
        """Store a serialised verdict dict in the cache."""
        with self._lock:
            k = self._key(content_hash, reviewer_id)
            self._cache[k] = verdict_dict
            self._stats.size = len(self._cache)

    def clear(self) -> None:
        """Drop all entries and reset stats."""
        with self._lock:
            self._cache.clear()
            self._stats = CacheStats()

    @property
    def stats(self) -> CacheStats:
        """Return a snapshot of cache statistics."""
        return self._stats


# Module-level singleton
_review_cache = CriticReviewCache()


def get_review_cache() -> CriticReviewCache:
    """Return the module-level review cache singleton."""
    return _review_cache
