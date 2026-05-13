---
id: "024-11"
title: "Consolidate Duplicate _PLUGINS_LOADED Flags (P1)"
status: closed
epic: "024"
labels: ["bug", "plugins", "P1", "correctness", "state-management"]
created: "2026-05-18"
closed: "2026-05-18"
priority: "P1"
---

## Summary

Finding 2.2 — Two independent `_PLUGINS_LOADED` globals in `plugins/__init__.py` and `command_handler.py`. If tests clear one but not the other, results diverge. Fix: move all idempotency to `plugins.load_plugin_callbacks`; `command_handler` just calls it, no local flag.

## What

Remove `_PLUGINS_LOADED` from `command_handler.py` and the `_ensure_plugins_loaded` wrapper that checks it. Make `plugins.load_plugin_callbacks` the single source of truth for plugin-load idempotency. `command_handler` imports and calls `load_plugin_callbacks` directly.

## Deliverables

- [x] `_PLUGINS_LOADED` global removed from `command_handler.py`
- [x] `_ensure_plugins_loaded` delegates entirely to `plugins.load_plugin_callbacks()`
- [x] `ruff check` passes on changed file
- [x] Module imports correctly from Python

## Acceptance Criteria

- [x] Plugins only loaded once regardless of which module triggers loading
- [x] Tests that monkeypatch plugin state work correctly without needing to reset two flags
- [x] No behavioral change in plugin loading
- [x] lint passes
- [x] import passes

## Dependencies

Parent: [Epic 024](024-epic-code-health.md)

## Estimated Effort

~30 lines changed, 20 minutes
