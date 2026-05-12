# cython: language_level=3
"""ScanCache core — thread-safe LRU cache for filesystem scan results."""

import logging
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from code_muse.fs_scan_cache.ttl_policy import is_fresh

logger = logging.getLogger(__name__)


@dataclass
class GlobMatch:
    """A single filesystem entry returned by a scan."""

    path: str
    file_type: str  # "file" | "dir" | "symlink"
    mtime: float
    size: int


@dataclass
class ScanEntry:
    """Internal cached scan result with timestamp."""

    entries: list[GlobMatch]
    created_at: float


@dataclass
class CacheStats:
    """Hit/miss/eviction statistics."""

    hits: int = 0
    misses: int = 0
    evictions: int = 0
    size: int = 0


class ScanCache:
    """Thread-safe LRU cache for filesystem scan results.

    Keyed by a hashable partition tuple (typically ``(root, hidden, gitignore,
    node_modules)``).  Max 16 entries, LRU eviction.  TTL-based freshness with
    separate fast-recheck for empty results.
    """

    def __init__(self, max_entries: int = 16) -> None:
        if max_entries < 1:
            raise ValueError("max_entries must be positive")
        self.max_entries = max_entries
        # FREE-THREADED: Generic scan cache — may be accessed from sync or async code.
        # Keep threading.Lock; migrate to asyncio.Lock only if all callers are async.
        self._lock = threading.Lock()
        self._cache: OrderedDict[tuple, ScanEntry] = OrderedDict()
        self._stats = CacheStats()

    def get_or_scan(
        self,
        key: tuple,
        scanner_fn: Callable[[], list[GlobMatch]],
    ) -> tuple[list[GlobMatch], float]:
        """Return cached entries if fresh, otherwise call *scanner_fn*.

        The scanner function is invoked **outside** the lock to avoid holding
        it during I/O.  A double-check is performed after re-acquiring the lock.

        Returns:
            ``(entries, cache_age_ms)`` — *cache_age_ms* is ``0.0`` for a
            fresh insertion, otherwise the monotonic age of the cached entry.
        """
        cdef double now = time.monotonic()
        cdef double age_ms
        cdef double created
        cdef object entry
        cdef list scanned
        cdef int evict_count
        cdef object new_entry

        with self._lock:
            if key in self._cache:
                entry = self._cache[key]
                if is_fresh(entry, now):
                    self._cache.move_to_end(key)
                    age_ms = (now - entry.created_at) * 1000.0
                    self._stats.hits += 1
                    self._stats.size = len(self._cache)
                    return (entry.entries, age_ms)
                # Stale — remove now so we don't return stale data later
                del self._cache[key]

        # Slow path: scan outside the lock
        scanned = scanner_fn()

        with self._lock:
            # Double-check: another thread may have populated while we scanned
            if key in self._cache:
                entry = self._cache[key]
                if is_fresh(entry, now):
                    self._cache.move_to_end(key)
                    age_ms = (now - entry.created_at) * 1000.0
                    self._stats.hits += 1
                    self._stats.size = len(self._cache)
                    return (entry.entries, age_ms)
                del self._cache[key]

            # Evict oldest if at capacity
            evict_count = 0
            while len(self._cache) >= self.max_entries:
                self._cache.popitem(last=False)
                evict_count += 1
            if evict_count:
                self._stats.evictions += evict_count

            created = time.monotonic()
            new_entry = ScanEntry(entries=scanned, created_at=created)
            self._cache[key] = new_entry
            self._stats.misses += 1
            self._stats.size = len(self._cache)
            return (new_entry.entries, 0.0)

    def invalidate(self, root: str | None = None) -> None:
        """Remove cache entries affected by *root*.

        If *root* is ``None``, clear the entire cache.  Otherwise remove any
        entry whose cached root is an ancestor of *root* or vice versa.
        """
        cdef list keys_to_remove
        cdef tuple key
        cdef object target
        cdef object cached_root
        cdef bint cached_is_ancestor
        cdef bint target_is_ancestor

        with self._lock:
            if root is None:
                self._cache.clear()
                self._stats.size = 0
                logger.debug("ScanCache cleared entirely")
                return

            target = Path(root).resolve()
            keys_to_remove = []
            for key in list(self._cache.keys()):
                cached_root = Path(key[0]).resolve()
                # Ancestor check in both directions
                try:
                    cached_is_ancestor = target.is_relative_to(cached_root)
                except AttributeError:
                    # Python < 3.12 fallback
                    try:
                        cached_is_ancestor = (
                            target == cached_root or cached_root in target.parents
                        )
                    except ValueError:
                        cached_is_ancestor = False

                try:
                    target_is_ancestor = cached_root.is_relative_to(target)
                except AttributeError:
                    try:
                        target_is_ancestor = (
                            cached_root == target or target in cached_root.parents
                        )
                    except ValueError:
                        target_is_ancestor = False

                if cached_is_ancestor or target_is_ancestor:
                    keys_to_remove.append(key)

            for key in keys_to_remove:
                del self._cache[key]
                logger.debug(f"ScanCache invalidated key {key}")

            self._stats.size = len(self._cache)

    def invalidate_for_path(self, path: str) -> None:
        """Invalidate cache entries related to *path*.

        Convenience wrapper around :meth:`invalidate` that accepts a file
        or directory path directly.
        """
        self.invalidate(path)

    def clear(self) -> None:
        """Remove all entries."""
        self.invalidate(None)

    @property
    def stats(self) -> CacheStats:
        """Return a snapshot of cache statistics."""
        with self._lock:
            return CacheStats(
                hits=self._stats.hits,
                misses=self._stats.misses,
                evictions=self._stats.evictions,
                size=self._stats.size,
            )
