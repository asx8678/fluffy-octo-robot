---
id: "017"
title: "Epic: Filesystem Scan Cache — TTL-Based Directory Entry Cache for Glob/Grep/Find"
status: closed
epic: "017"
labels: ["epic", "cache", "filesystem", "scan", "glob", "grep", "P3"]
created: "2025-07-14"
priority: "P3"
---

## Summary

Port Oh-My-Pi's fs_cache.rs. DashMap-based concurrent cache for directory scans, partitioned by root + hidden + gitignore + node_modules flags. TTL-based freshness with fast empty-result recheck. Used by glob, fuzzyFind, and grep.

## Motivation

Repeated directory walks for glob/grep/find waste time. A shared scan cache with TTL avoids redundant filesystem traversal.

## Deliverables

1. ScanCache class (DashMap or dict+Locks, partition-keyed)
2. TTL + empty-result recheck policy
3. Invalidation API (agent file mutations trigger cache clear)
4. Integration with glob/grep/find tools

## Acceptance Criteria

- [x] Cache keyed by (root, hidden, gitignore, node_modules) tuple
- [x] Entries expire after TTL (default 1000ms)
- [x] Empty results rechecked faster (200ms)
- [x] Max 16 entries to prevent unbounded growth
- [x] Agent write_file/replace invalidates cache for affected directories
- [x] glob/grep/find use cache via get_or_scan when available

## Dependencies

None. Standalone utility.

## Estimated Effort

~300 lines, 2.5 hours

## Children

- [017-01](017-01-scan-cache-core.md) — ScanCache Core (partition key, DashMap/dict, TTL tracking)
- [017-02](017-02-ttl-empty-recheck.md) — TTL + Empty-Recheck Policy (CACHE_TTL_MS, EMPTY_RECHECK_MS, MAX_CACHE_ENTRIES)
- [017-03](017-03-invalidation-hooks.md) — Invalidation Hooks (write_file/replace trigger cache clear)
- [017-04](017-04-tool-integration.md) — Tool Integration (glob, grep, find use get_or_scan)
