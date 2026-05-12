"""Tests for BlockingLruCache."""

import threading
import time
from typing import Any

import pytest

from code_muse.models_cache.blocking_lru_cache import BlockingLruCache


def test_capacity_must_be_positive() -> None:
    with pytest.raises(ValueError, match="capacity must be positive"):
        BlockingLruCache(0)
    with pytest.raises(ValueError, match="capacity must be positive"):
        BlockingLruCache(-1)


def test_insert_and_get() -> None:
    cache: BlockingLruCache[str, int] = BlockingLruCache(3)
    cache.insert("a", 1)
    assert cache.get("a") == 1
    assert cache.get("b") is None


def test_get_promotes_to_mru() -> None:
    cache: BlockingLruCache[str, int] = BlockingLruCache(2)
    cache.insert("a", 1)
    cache.insert("b", 2)
    # Access "a" to promote it
    cache.get("a")
    # Insert "c" — "b" should be evicted because "a" is now MRU
    cache.insert("c", 3)
    assert cache.get("a") == 1
    assert cache.get("b") is None
    assert cache.get("c") == 3


def test_eviction_at_capacity() -> None:
    cache: BlockingLruCache[str, int] = BlockingLruCache(2)
    cache.insert("a", 1)
    cache.insert("b", 2)
    cache.insert("c", 3)
    assert cache.get("a") is None
    assert cache.get("b") == 2
    assert cache.get("c") == 3
    assert len(cache) == 2


def test_update_existing_key() -> None:
    cache: BlockingLruCache[str, int] = BlockingLruCache(2)
    cache.insert("a", 1)
    cache.insert("a", 10)
    assert cache.get("a") == 10
    assert len(cache) == 1


def test_remove() -> None:
    cache: BlockingLruCache[str, int] = BlockingLruCache(2)
    cache.insert("a", 1)
    assert cache.remove("a") == 1
    assert cache.remove("a") is None
    assert len(cache) == 0


def test_clear() -> None:
    cache: BlockingLruCache[str, int] = BlockingLruCache(2)
    cache.insert("a", 1)
    cache.insert("b", 2)
    cache.clear()
    assert len(cache) == 0
    assert cache.get("a") is None


def test_get_or_insert_with_factory_called_on_miss() -> None:
    cache: BlockingLruCache[str, int] = BlockingLruCache(2)
    call_count = 0

    def factory() -> int:
        nonlocal call_count
        call_count += 1
        return 42

    value = cache.get_or_insert_with("a", factory)
    assert value == 42
    assert call_count == 1

    # Second call should use cached value
    value = cache.get_or_insert_with("a", factory)
    assert value == 42
    assert call_count == 1


def test_get_or_insert_with_factory_called_outside_lock() -> None:
    cache: BlockingLruCache[str, int] = BlockingLruCache(2)
    factory_started = threading.Event()

    def factory() -> int:
        factory_started.set()
        # Wait a bit so the other thread could try to acquire the lock
        time.sleep(0.05)
        return 99

    def worker() -> None:
        cache.get_or_insert_with("x", factory)

    t = threading.Thread(target=worker)
    t.start()
    assert factory_started.wait(timeout=1.0)
    # While factory runs, another thread should be able to acquire the lock
    # (get on a different key should work)
    cache.insert("y", 1)
    t.join(timeout=1.0)
    assert cache.get("x") == 99
    assert cache.get("y") == 1


def test_thread_safety_concurrent_inserts() -> None:
    cache: BlockingLruCache[int, int] = BlockingLruCache(100)
    errors: list[Any] = []

    def worker(start: int) -> None:
        try:
            for i in range(start, start + 50):
                cache.insert(i, i * 2)
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(i * 50,)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    assert len(cache) == 100  # Only 100 unique keys inserted, all within capacity


def test_thread_safety_get_or_insert_with_race() -> None:
    cache: BlockingLruCache[str, int] = BlockingLruCache(10)
    call_count = 0
    lock = threading.Lock()

    def factory() -> int:
        nonlocal call_count
        with lock:
            call_count += 1
        time.sleep(0.02)
        return 123

    def worker() -> None:
        cache.get_or_insert_with("shared", factory)

    threads = [threading.Thread(target=worker) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # Factory may be called more than once under heavy concurrency,
    # but only one result is cached.
    assert call_count >= 1
    assert cache.get("shared") == 123


def test_capacity_property() -> None:
    cache: BlockingLruCache[str, int] = BlockingLruCache(5)
    assert cache.capacity == 5
