---
id: "017-02"
title: "TTL + Empty-Recheck Policy — Environment-Configurable Freshness Rules"
status: "open"
epic: "017"
labels: ["cache", "ttl", "policy", "empty", "recheck", "P3"]
created: "2025-07-14"
priority: "P3"
---

## Summary

Implement TTL-based freshness with separate empty-result fast recheck. Configuration via environment variables: FS_SCAN_CACHE_TTL_MS (default 1000ms), FS_SCAN_EMPTY_RECHECK_MS (default 200ms). On cache hit within TTL: return entries. On expired hit: evict and rescan. On empty result: recheck more aggressively (200ms vs 1000ms) to avoid stale negatives. TTL=0 bypasses cache entirely.

## Motivation

Different freshness requirements: populated results can be cached longer, empty results need faster revalidation to avoid missing newly-created files.

## Deliverables

- Cache freshness logic in get_or_scan
- env_uint helpers for reading millisecond config values
- Bypass when TTL=0

## Acceptance Criteria

- [x] TTL honored for non-empty results
- [x] empty results rechecked faster
- [x] TTL=0 bypasses cache
- [x] env vars override defaults
- [x] cache_age_ms accurate

## Dependencies

Parent [Epic 017](017-epic-fs-scan-cache.md), depends on 017-01.

## Estimated Effort

~60 lines, 30 min.
