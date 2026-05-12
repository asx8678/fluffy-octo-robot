---
id: "019-03"
title: "Register New Strategy Categories for Content Types"
status: open
epic: "019"
labels: ["content-router", "registry", "strategies", "P1"]
created: "2025-07-16"
priority: "P1"
---

## Summary

Register `json`, `diff`, `log`, `html`, and `search` strategy categories in the `StrategyRegistry` so the content router has target strategies to route to. Initially these can be stubs that passthrough, then filled by Epic 020 (SmartCrusher) and Epic 021 (CodeCompressor).

## Motivation

Content router needs valid strategy categories to route to. Without registered strategies, detection is useless. Stub strategies allow incremental implementation.

## Deliverables

- Register `json` category (stub: passthrough until SmartCrusher)
- Register `diff` category (stub: basic diff compaction)
- Register `log` category (stub: basic log dedup)
- Register `html` category (stub: tag strip)
- Register `search` category (stub: field filter)
- Update `StrategyRegistry.list_categories()` to include new entries

## Acceptance Criteria

- [ ] `json` category registered with stub strategy
- [ ] `diff` category registered with stub strategy
- [ ] `log` category registered with stub strategy
- [ ] `html` category registered with stub strategy
- [ ] `search` category registered with stub strategy
- [ ] Registry does not error when content router requests these categories

## Dependencies

Parent: [Epic 019](019-epic-content-router.md)

## Estimated Effort

~60 lines, 30 min
