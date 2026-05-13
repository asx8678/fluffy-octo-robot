---
id: "024-14"
title: "Plugin System: Load Performance & Atomic Registration (P2)"
status: open
epic: "024"
labels: ["performance", "plugins", "P2"]
created: "2026-05-18"
priority: "P2"
---

## Summary

Two issues in `plugins/__init__.py`:
1. `compute_plugin_hash` does full `rglob` + SHA-256 on every load, even when nothing changed.
2. `register_callback` runs at module import with no transaction — partial failures leave orphan registrations.
Fix: mtime/size short-circuit cache for hash; deferred/atomic commit for registrations.

## What

Cache plugin hash by `(mtime, size)` key; only recompute SHA-256 when metadata changes. Wrap `register_callback` calls in a deferred commit: collect all registrations during plugin load, validate, then commit atomically. On failure, rollback partial state.

## Deliverables

- [ ] Hash cached by mtime/size key
- [ ] Registrations committed atomically on full success
- [ ] Tests pass

## Acceptance Criteria

- [ ] `compute_plugin_hash` short-circuits when mtime/size unchanged
- [ ] Partial plugin failure does not leave orphan callbacks
- [ ] Load time reduced when plugins unchanged
- [ ] All tests pass

## Dependencies

Parent: [Epic 024](024-epic-code-health.md)

## Estimated Effort

~100 lines changed, 1.5 hours
