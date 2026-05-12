---
id: "012-04"
title: "Startup Cache Integration — Load Cached Models on Session Start"
status: closed
epic: "012"
labels: ["startup", "integration", "cache", "models", "P1"]
created: "2025-07-14"
priority: "P1"
---

## Summary

At session startup, check models_cache.json freshness (< 24 hours old). If fresh, use cached models; if stale or missing, fetch from network and update cache.

## Motivation

Reduces startup latency when models haven't changed recently. Cache freshness prevents stale model data.

## Deliverables

- Function load_cached_models() that checks cache age and returns models or None.
- Integration point in model factory startup sequence.

## Acceptance Criteria

- [x] fresh cache bypasses network
- [x] stale cache triggers update
- [x] missing cache triggers fetch
- [x] errors logged not fatal
- [x] startup time measurably faster on cache hit

## Dependencies

Parent: [Epic 012](012-epic-models-cache.md), depends on 012-01

## Estimated Effort

~40 lines, 20 min
