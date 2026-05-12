---
id: "020"
title: "Epic: SmartCrusher — JSON & Structured Data Compression"
status: open
epic: "020"
labels: ["epic", "smartcrusher", "P1", "json-compression", "headroom-port"]
created: "2025-07-16"
priority: "P1"
---

## Summary

Port headroom's SmartCrusher to muse — a universal JSON/structured data compressor that detects patterns in arrays of dicts, collapses nested objects, templates repeated structures, and selects informative fields. Cuts JSON token volume by 80-95%.

## Motivation

Tool outputs, API responses, config files, and `cat package.json` are all JSON. Currently they go through generic "code" comment-stripping or "unknown" passthrough. SmartCrusher reduces `cat package.json` from 2000 tokens to ~200.

## Source

Ported from **headroom**'s `SmartCrusher` — pattern detection (array templating, field selection, nested flattening, type-aware compaction).

## Deliverables

1. `SmartCrusher` strategy class — the core compression engine
2. Registration as `json` strategy in StrategyRegistry
3. Integration with Content Router (detected JSON output → SmartCrusher)
4. Pattern detection: array-of-dicts → template extraction, repeated keys → collapse, nested → flatten
5. Configurable aggressiveness via verbosity levels

## Acceptance Criteria

- [ ] `cat package.json` (typical npm package) → < 15% of original tokens
- [ ] `curl api.github.com/repos/...` → arrays collapsed to templates
- [ ] Nested objects flattened with key path notation
- [ ] Preserves all semantically meaningful fields (names, versions, URLs)
- [ ] Drops whitespace-only, boilerplate, and redundant structural tokens
- [ ] Verbosity level 0 = max compression, 4 = near-original

## Dependencies

- Epic 019 (Content Router) — routes JSON output here
- Epic 001 (Core Filter Engine) — strategy registry + dispatcher

## Estimated Effort

~350 lines, 3–4 hours

## Children

- [020-01](020-01-json-pattern-detection.md)
- [020-02](020-02-json-compressor-core.md)
- [020-03](020-03-smartcrusher-integration.md)
