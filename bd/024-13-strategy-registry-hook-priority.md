---
id: "024-13"
title: "Strategy Registry Log Levels & Hook Priority Cleanup (P2)"
status: closed
epic: "024"
labels: ["cleanup", "logging", "hooks", "P2"]
created: "2026-05-18"
priority: "P2"
---

## Summary

Two findings:
1. `StrategyRegistry` logs both winning and losing overrides at `warning` level in `registry.py`.
2. `post_tool_call` execution order depends on directory iteration in `semantic_compression`.

## What

Downgrade winning-override and losing-override logs to `debug`. Upgrade equal-priority collisions to `warning`. Add explicit priority metadata to `post_tool_call` hooks in `semantic_compression` so execution order is deterministic and independent of filesystem iteration.

## Deliverables

- [ ] Overrides logged at `debug`
- [ ] Equal-priority collisions logged at `warning`
- [ ] Explicit priority on `post_tool_call`
- [ ] Tests pass

## Acceptance Criteria

- [ ] `StrategyRegistry` only emits `warning` for true conflicts (equal priority)
- [ ] Routine override logging at `debug`
- [ ] `post_tool_call` hook order stable across restarts / platforms
- [ ] All tests pass

## Dependencies

Parent: [Epic 024](024-epic-code-health.md)

## Estimated Effort

~60 lines changed, 45 minutes
