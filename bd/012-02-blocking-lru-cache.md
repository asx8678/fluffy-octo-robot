---
id: "012-02"
title: "Generic LRU Cache — Thread-Safe BlockingLruCache with get_or_insert_with"
status: closed
epic: "012"
labels: ["cache", "lru", "generic", "thread-safe", "P1"]
created: "2025-07-14"
priority: "P1"
---

## Summary

Implement a thread-safe LRU cache with NonZeroUsize capacity. Core methods: get_or_insert_with(key, factory) → value (cached or newly computed), get_or_try_insert_with(key, factory) → Result, get, insert, remove, clear, with_mut. Uses threading.Lock for thread safety. Gracefully no-ops when no runtime context is available.

## Motivation

Muse lacks a general-purpose thread-safe cache. This is needed for models cache, scan cache, and any future caching needs.

## Deliverables

- `BlockingLruCache[K, V]` generic class
- Internal LRU eviction via collections.OrderedDict

## Acceptance Criteria

- [x] stores and retrieves values correctly
- [x] evicts least-recently-used at capacity
- [x] get_or_insert_with calls factory only on miss
- [x] thread-safe under concurrent access
- [x] works without tokio/asyncio runtime

## Dependencies

Parent [Epic 012](012-epic-models-cache.md).

## Estimated Effort

~80 lines, 40 min.
