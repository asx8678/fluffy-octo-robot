---
id: "018-03"
title: "Cache Hit/Miss Tracking — Record Cache Read/Write Tokens per Turn"
status: "open"
epic: "018"
labels: ["token", "cache", "tracking", "hit", "miss", "P3"]
created: "2025-07-14"
priority: "P3"
---

## Summary

After each Anthropic API call, parse the response usage data to extract: cache_read_input_tokens (tokens read from cache), cache_creation_input_tokens (new tokens written to cache), total input_tokens. Store per-turn and aggregate across session. Feed data into the token tracking database (Epic 006) for historical reporting and /stats display.

## Motivation

Users need to see cache effectiveness. Tracking enables cost attribution and optimization of the cache breakpoint.

## Deliverables

- `extract_cache_usage(response: dict) → CacheUsage`
- `CacheUsage` dataclass with read_tokens, write_tokens, total_tokens
- Integration with token tracker

## Acceptance Criteria

- [x] cache tokens extracted from API response
- [x] stored in tracking database
- [x] aggregated per session
- [x] shown in /stats output
- [x] handles responses without cache data

## Dependencies

Parent [Epic 018](018-epic-token-caching.md), depends on 018-02, 006.

## Estimated Effort

~50 lines, 25 min.
