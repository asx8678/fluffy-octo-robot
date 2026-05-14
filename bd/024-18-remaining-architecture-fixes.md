---
id: "024-18"
title: "Remaining Architecture: load_prompt Gating & Config Coupling (P3)"
status: closed
epic: "024"
labels: ["architecture", "config", "P3"]
created: "2026-05-18"
priority: "P3"
---

## Summary

Two findings:
1. `load_prompt` returns compression instructions unconditionally for every agent (Finding 2.5).
2. Agent classes call `get_puppy_name`/`get_owner_name` from global config (Finding 2.8).

## What

Add a config flag (default `false`) that gates whether `load_prompt` injects compression instructions. Update agent constructors to accept `puppy_name` and `owner_name` parameters, falling back to config only when not provided.

## Deliverables

- [ ] Compression prompt gated on config flag (default off)
- [ ] Agents accept names at construction
- [ ] Tests pass

## Acceptance Criteria

- [ ] `load_prompt` only includes compression instructions when config flag is enabled
- [ ] Agents can be instantiated with explicit names, no global config dependency
- [ ] Backward compatibility: existing code paths still work via config fallback
- [ ] All tests pass

## Dependencies

Parent: [Epic 024](024-epic-code-health.md)

## Estimated Effort

~80 lines changed, 1 hour
