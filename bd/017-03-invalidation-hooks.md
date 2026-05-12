---
id: "017-03"
title: "Invalidation Hooks — Clear Cache on File Mutations + Branch Changes"
status: "open"
epic: "017"
labels: ["cache", "invalidation", "hook", "mutation", "P3"]
created: "2025-07-14"
priority: "P3"
---

## Summary

After agent calls write_file or replace_in_file, invalidate any cache entries whose root path is an ancestor of the modified file. Use path resolution: for each cache key, check if modified_path.is_relative_to(cache_root) or vice versa. Also invalidate on git branch switch (checkout). Invalidation must be thread-safe (acquire cache lock during mutation).

## Motivation

Stale cache entries after file modifications would return incorrect results. Automatic invalidation keeps cache accurate.

## Deliverables

- `invalidate_for_path(modified_path: Path)` function
- Hook into write_file/replace_in_file post-execution
- Optional git checkout hook

## Acceptance Criteria

- [x] file modifications invalidate ancestor caches
- [x] thread-safe invalidation
- [x] directory creation invalidates parent cache
- [x] branch switch invalidates all project caches
- [x] invalidation logged for debugging

## Dependencies

Parent [Epic 017](017-epic-fs-scan-cache.md), depends on 017-01.

## Estimated Effort

~80 lines, 40 min.
