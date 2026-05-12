---
id: "017-01"
title: "ScanCache Core — Partition-Keyed Directory Entry Cache with Eviction"
status: "open"
epic: "017"
labels: ["cache", "filesystem", "scan", "core", "P3"]
created: "2025-07-14"
priority: "P3"
---

## Summary

Implement the core ScanCache class. Cache entries are keyed by a partition tuple: (root: Path, include_hidden: bool, use_gitignore: bool, skip_node_modules: bool). Each entry stores: entries list[GlobMatch], created_at float timestamp. Maximum 16 entries with oldest-first eviction (LRU). get_or_scan(key, scanner_fn) method: if key present and fresh, return cached entries + cache_age_ms; otherwise run scanner_fn, store result, return fresh entries. Thread-safe via Lock.

## Motivation

Repeated directory walks for glob/grep/find waste time. A shared scan cache avoids redundant filesystem traversal across tool calls.

## Deliverables

- `ScanCache` class with get_or_scan, invalidate, clear methods
- `GlobMatch` dataclass (path, file_type, mtime, size)
- Cache stats (hits, misses, evictions)

## Acceptance Criteria

- [x] entries keyed by full partition tuple
- [x] max 16 entries enforced
- [x] oldest evicted first
- [x] get_or_scan returns cache_age_ms
- [x] thread-safe under concurrent access
- [x] cache stats tracked

## Dependencies

Parent [Epic 017](017-epic-fs-scan-cache.md).

## Estimated Effort

~100 lines, 45 min.
