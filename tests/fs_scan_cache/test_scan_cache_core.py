"""Tests for fs_scan_cache core."""

import threading
import time
from typing import Any

import pytest
from code_muse.fs_scan_cache.scan_cache_core import (
    GlobMatch,
    ScanCache,
)


def test_glob_match_creation() -> None:
    m = GlobMatch(path="/a/b.py", file_type="file", mtime=1.0, size=100)
    assert m.path == "/a/b.py"
    assert m.file_type == "file"


def test_scan_cache_hit() -> None:
    cache = ScanCache(max_entries=4)
    call_count = 0

    def scanner() -> list[GlobMatch]:
        nonlocal call_count
        call_count += 1
        return [GlobMatch(path="/a.py", file_type="file", mtime=1.0, size=10)]

    entries, age = cache.get_or_scan(("/", False, True, True), scanner)
    assert len(entries) == 1
    assert age == 0.0
    assert call_count == 1
    assert cache.stats.misses == 1
    assert cache.stats.hits == 0

    # Second call should hit
    entries2, age2 = cache.get_or_scan(("/", False, True, True), scanner)
    assert len(entries2) == 1
    assert age2 > 0.0
    assert call_count == 1
    assert cache.stats.misses == 1
    assert cache.stats.hits == 1


def test_scan_cache_miss_after_ttl() -> None:
    cache = ScanCache(max_entries=4)
    call_count = 0

    def scanner() -> list[GlobMatch]:
        nonlocal call_count
        call_count += 1
        return [GlobMatch(path="/a.py", file_type="file", mtime=1.0, size=10)]

    cache.get_or_scan(("/", False, True, True), scanner)
    assert call_count == 1

    # Wait for TTL to expire
    time.sleep(1.2)
    entries, age = cache.get_or_scan(("/", False, True, True), scanner)
    assert call_count == 2
    assert age == 0.0


def test_scan_cache_lru_eviction() -> None:
    cache = ScanCache(max_entries=3)

    def make_scanner(idx: int) -> Any:
        def scanner() -> list[GlobMatch]:
            return [GlobMatch(path=f"/{idx}.py", file_type="file", mtime=1.0, size=10)]

        return scanner

    # Fill cache to capacity
    for i in range(3):
        cache.get_or_scan((f"/root{i}", False, True, True), make_scanner(i))

    assert cache.stats.size == 3
    assert cache.stats.evictions == 0

    # Access root0 to make it MRU
    cache.get_or_scan(("/root0", False, True, True), make_scanner(0))

    # Insert root3 — should evict root1 (LRU)
    cache.get_or_scan(("/root3", False, True, True), make_scanner(3))
    assert cache.stats.evictions == 1
    assert cache.stats.size == 3

    # root0 and root2 should remain; root1 evicted
    assert cache.get_or_scan(("/root0", False, True, True), make_scanner(0))[1] > 0.0
    assert cache.get_or_scan(("/root2", False, True, True), make_scanner(2))[1] > 0.0
    # root1 should trigger a new scan (miss)
    _, age = cache.get_or_scan(("/root1", False, True, True), make_scanner(1))
    assert age == 0.0


def test_scan_cache_thread_safety() -> None:
    cache = ScanCache(max_entries=16)
    call_count = 0
    lock = threading.Lock()

    def scanner() -> list[GlobMatch]:
        nonlocal call_count
        with lock:
            call_count += 1
        time.sleep(0.02)
        return [GlobMatch(path="/shared.py", file_type="file", mtime=1.0, size=10)]

    def worker() -> None:
        cache.get_or_scan(("/shared", False, True, True), scanner)

    threads = [threading.Thread(target=worker) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # Factory may be called more than once under contention, but only one
    # value is cached and all threads see a hit after the first insertion.
    assert call_count >= 1
    stats = cache.stats
    assert stats.hits + stats.misses == 10
    assert stats.misses >= 1


def test_scan_cache_clear() -> None:
    cache = ScanCache()

    def scanner() -> list[GlobMatch]:
        return [GlobMatch(path="/a.py", file_type="file", mtime=1.0, size=10)]

    cache.get_or_scan(("/", False, True, True), scanner)
    assert cache.stats.size == 1
    cache.clear()
    assert cache.stats.size == 0


def test_scan_cache_invalidate_all() -> None:
    cache = ScanCache()

    def scanner() -> list[GlobMatch]:
        return [GlobMatch(path="/a.py", file_type="file", mtime=1.0, size=10)]

    cache.get_or_scan(("/a", False, True, True), scanner)
    cache.get_or_scan(("/b", False, True, True), scanner)
    assert cache.stats.size == 2
    cache.invalidate(None)
    assert cache.stats.size == 0


def test_scan_cache_invalidate_by_ancestor() -> None:
    cache = ScanCache()

    def scanner() -> list[GlobMatch]:
        return [GlobMatch(path="/a.py", file_type="file", mtime=1.0, size=10)]

    cache.get_or_scan(("/project/src", False, True, True), scanner)
    cache.get_or_scan(("/project/tests", False, True, True), scanner)
    cache.get_or_scan(("/other", False, True, True), scanner)
    assert cache.stats.size == 3

    # Invalidating /project should remove src and tests
    cache.invalidate("/project")
    assert cache.stats.size == 1
    # Verify the remaining entry
    _, age = cache.get_or_scan(("/other", False, True, True), scanner)
    assert age > 0.0


def test_scan_cache_invalidate_by_descendant() -> None:
    cache = ScanCache()

    def scanner() -> list[GlobMatch]:
        return [GlobMatch(path="/a.py", file_type="file", mtime=1.0, size=10)]

    cache.get_or_scan(("/project", False, True, True), scanner)
    cache.get_or_scan(("/other", False, True, True), scanner)
    assert cache.stats.size == 2

    # Invalidating /project/src/main.py should also remove /project
    cache.invalidate("/project/src/main.py")
    assert cache.stats.size == 1
    _, age = cache.get_or_scan(("/other", False, True, True), scanner)
    assert age > 0.0


def test_scan_cache_capacity_must_be_positive() -> None:
    with pytest.raises(ValueError, match="max_entries must be positive"):
        ScanCache(0)
    with pytest.raises(ValueError, match="max_entries must be positive"):
        ScanCache(-1)


def test_scan_cache_empty_result_fast_recheck() -> None:
    cache = ScanCache(max_entries=4)
    call_count = 0

    def scanner() -> list[GlobMatch]:
        nonlocal call_count
        call_count += 1
        return []

    cache.get_or_scan(("/empty", False, True, True), scanner)
    assert call_count == 1

    # Immediately request again — empty results recheck faster (200ms default)
    # so this should still be fresh
    time.sleep(0.05)
    _, age = cache.get_or_scan(("/empty", False, True, True), scanner)
    assert age > 0.0
    assert call_count == 1

    # Wait longer than EMPTY_RECHECK_MS
    time.sleep(0.25)
    _, age = cache.get_or_scan(("/empty", False, True, True), scanner)
    assert age == 0.0
    assert call_count == 2


def test_scan_cache_stats_immutable_snapshot() -> None:
    cache = ScanCache()

    def scanner() -> list[GlobMatch]:
        return [GlobMatch(path="/a.py", file_type="file", mtime=1.0, size=10)]

    cache.get_or_scan(("/", False, True, True), scanner)
    stats1 = cache.stats
    cache.get_or_scan(("/", False, True, True), scanner)
    stats2 = cache.stats
    assert stats1.hits == 0
    assert stats2.hits == 1


def test_scan_cache_double_check_after_stale_removal() -> None:
    cache = ScanCache(max_entries=4)

    def scanner() -> list[GlobMatch]:
        return [GlobMatch(path="/a.py", file_type="file", mtime=1.0, size=10)]

    key = ("/", False, True, True)
    cache.get_or_scan(key, scanner)
    time.sleep(1.2)

    # Stale entry was removed under lock; new scan should insert fresh data
    entries, age = cache.get_or_scan(key, scanner)
    assert age == 0.0
    assert len(entries) == 1
