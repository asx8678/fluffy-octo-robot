---
id: "001-02"
title: "Strategy Registry with Plugin-Style Registration"
status: closed
epic: "001"
labels: ["filter-engine", "registry", "plugin", "dispatcher", "core", "P0"]
created: "2025-07-14"
priority: "P0"
---

## Summary

Build a strategy registry that allows filtering strategies to self-register via callbacks, keeping the core engine decoupled from strategy implementations.

## Motivation

Plugin-style registration means new strategies can be added without touching the dispatcher or classifier. This is critical for maintainability and third-party extensions.

## Deliverables

- Registry class/dict with `register(category, strategy_fn)` API
- `get_strategy(category)` lookup
- Support for strategy priority / override

## Acceptance Criteria

- [x] Strategies register themselves at import time or init time
- [x] Registry returns the matching strategy function for a category
- [x] Duplicate registrations are handled (warn or override)
- [x] Unregistered categories fall back to passthrough
- [x] Registry is testable in isolation

## Dependencies

Parent: [Epic 001](001-epic-filter-engine.md) — Core Filter Engine

## Estimated Effort

~80 lines, 45 minutes
