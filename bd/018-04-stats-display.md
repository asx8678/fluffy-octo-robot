---
id: "018-04"
title: "Stats Display Integration — Show Cached Token Savings in /stats Output"
status: "closed"
epic: "018"
labels: ["token", "cache", "stats", "display", "P3"]
created: "2025-07-14"
priority: "P3"
---

## Summary

Extend the /stats command output (from Epic 006 token tracking) to include a new "Token Caching" section. Display: cache_read_tokens (tokens served from cache), cache_write_tokens (new cache entries created), cache_hit_rate (read / total input %), estimated cost savings in USD based on Anthropic pricing (cache read = 0.1x base, cache write = 1.25x base). Handle missing data gracefully (show "caching not available for this session").

## Motivation

Cache savings should be visible alongside other token stats. Cost estimates make the value of caching concrete.

## Deliverables

- Enhanced /stats output with cache section
- Cost calculation using pricing constants
- Graceful fallback for non-cached sessions

## Acceptance Criteria

- [x] cache section present in /stats
- [x] hit rate percentage calculated
- [x] cost savings estimated correctly
- [x] handles sessions without cache
- [x] compact LLM-readable format

## Dependencies

Parent [Epic 018](018-epic-token-caching.md), depends on 018-03, 006.

## Estimated Effort

~50 lines, 25 min.
