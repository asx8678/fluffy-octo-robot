---
id: "017-04"
title: "Tool Integration — Wire ScanCache into Glob, Grep, and FuzzyFind Tools"
status: "open"
epic: "017"
labels: ["cache", "integration", "glob", "grep", "find", "P3"]
created: "2025-07-14"
priority: "P3"
---

## Summary

Add optional cache=True parameter to glob, grep, and fuzzyFind tool schemas. When cache enabled, tool calls ScanCache.get_or_scan instead of direct filesystem walk. Return cache_age_ms in tool output metadata so the agent can know data freshness. Handle cache miss gracefully (fall through to direct scan). Make cache opt-in per call (default: cache=False for backward compatibility).

## Motivation

Tools should be able to leverage the scan cache without forcing it. Opt-in allows agent to decide when cached results are acceptable.

## Deliverables

- Modified tool schemas with cache parameter
- Integration points in glob/grep/fuzzyFind implementations
- cache_age_ms in response metadata

## Acceptance Criteria

- [x] cache=True uses scan cache
- [x] cache=False does direct walk
- [x] cache miss falls through
- [x] cache_age_ms included in response
- [x] backward compatible (existing calls unchanged)

## Dependencies

Parent [Epic 017](017-epic-fs-scan-cache.md), depends on 017-01.

## Estimated Effort

~60 lines, 30 min.
