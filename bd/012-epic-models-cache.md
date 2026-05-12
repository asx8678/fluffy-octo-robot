---
id: "012"
title: "Epic: Models Cache + LRU Cache — Offline Model List + General-Purpose LRU"
status: closed
epic: "012"
labels: ["epic", "cache", "models", "lru", "startup", "P1"]
created: "2025-07-14"
priority: "P1"
---

## Summary

Port Codex's models_cache.json pattern and Oh-My-Pi's fs_cache LRU. Pre-seed model list at build time to avoid network fetch on cold start. General-purpose BlockingLruCache for response/tool-output caching.

## Motivation

Muse fetches model list on startup. A pre-seeded cache means faster cold starts. The LRU cache is a reusable utility for many caching needs.

## Deliverables

1. models_cache.json writer (convert models_dev_api.json → picker-visible models)
2. BlockingLruCache class (thread-safe, tokio-style, get_or_insert_with)
3. SHA-256 content hash helper for cache keys
4. Startup integration (load cache, skip network fetch if fresh)

## Acceptance Criteria

- [x] models_cache.json written with fetched_at timestamp + client_version
- [x] Cache used on startup when fresh (< 24h old)
- [x] LRU cache supports get_or_insert_with, get, insert, remove, clear
- [x] Thread-safe operation under concurrent access
- [x] Works outside tokio runtime (no-op async mode)

## Dependencies

None. Standalone.

## Estimated Effort

~200 lines, 1.5 hours

## Children

- [012-01](012-01-models-cache-writer.md) — models_cache.json Writer (preset→ModelInfo conversion, fetched_at, client_version)
- [012-02](012-02-blocking-lru-cache.md) — BlockingLruCache (NonZeroUsize capacity, Mutex-protected LruCache, get_or_insert_with)
- [012-03](012-03-sha256-hash.md) — SHA-256 Content Hash (sha256 digest for cache keys)
- [012-04](012-04-startup-integration.md) — Startup Integration (load cache, check freshness, skip network fetch)
