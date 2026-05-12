"""Thread-safe generic LRU cache using OrderedDict and threading.Lock.

FREE-THREADED: This cache uses threading.Lock because it may be accessed
from both sync and async contexts. If all callers become fully async,
consider switching to asyncio.Lock.
"""

import threading
from collections import OrderedDict
from collections.abc import Callable
from typing import TypeVar

K = TypeVar("K")
V = TypeVar("V")


class BlockingLruCache[K, V]:
    """Thread-safe LRU cache with get_or_insert_with pattern.

    Uses OrderedDict for O(1) LRU eviction and threading.Lock for
    thread safety. Capacity must be a positive integer (> 0).
    Gracefully works outside asyncio/tokio runtimes.
    """

    def __init__(self, capacity: int) -> None:
        if capacity < 1:
            raise ValueError("capacity must be positive")
        self._capacity = capacity
        # FREE-THREADED: Generic cache — may be accessed from sync or async code.
        # Keep threading.Lock; migrate to asyncio.Lock only if all callers are async.
        self._lock = threading.Lock()
        self._cache: OrderedDict[K, V] = OrderedDict()

    def get(self, key: K) -> V | None:
        """Return cached value or None. Promotes to MRU on hit."""
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                return self._cache[key]
            return None

    def get_or_insert_with(self, key: K, factory: Callable[[], V]) -> V:
        """Return cached value, or call factory on miss and cache it.

        The factory is called OUTSIDE the lock to avoid holding it during
        expensive computation. A double-check is performed under lock.
        """
        # Fast path: check cache under lock
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                return self._cache[key]

        # Slow path: compute outside lock
        value = factory()

        # Insert under lock with eviction check
        with self._lock:
            # Double-check: another thread may have inserted while we computed
            if key in self._cache:
                self._cache.move_to_end(key)
                return self._cache[key]

            # Evict oldest if at capacity
            while len(self._cache) >= self._capacity:
                self._cache.popitem(last=False)

            self._cache[key] = value
            return value

    def insert(self, key: K, value: V) -> None:
        """Insert a value, evicting oldest if at capacity."""
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                self._cache[key] = value
                return
            while len(self._cache) >= self._capacity:
                self._cache.popitem(last=False)
            self._cache[key] = value

    def remove(self, key: K) -> V | None:
        """Remove and return the value for key, or None."""
        with self._lock:
            return self._cache.pop(key, None)

    def clear(self) -> None:
        """Remove all entries."""
        with self._lock:
            self._cache.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._cache)

    @property
    def capacity(self) -> int:
        return self._capacity
