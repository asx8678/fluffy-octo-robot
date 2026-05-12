---
id: "008-05"
title: "Rewind Keyboard Shortcut"
status: closed
epic: "008"
labels: ["checkpointing", "rewind", "keyboard", "shortcut", "P0"]
created: "2025-07-14"
priority: "P0"
---

## Summary

Bind Esc×2 (double-press within 500ms) to open rewind UI. Same UI as /restore but accessible from any mode. Handle edge case: Esc single-press for cancel, double-press for rewind. Must not interfere with normal Esc behavior in editor/input modes.

## Motivation

A keyboard shortcut is faster than typing `/restore` when the user realizes they just made a mistake. Double-press Esc is a natural panic-undo gesture.

## Deliverables

- Esc double-press detector (500ms window)
- Rewind UI invocation (same as `/restore`)
- Single-press Esc still functions as cancel in editor/input modes
- No interference with existing Esc bindings

## Acceptance Criteria

- [x] Double-press Esc within 500ms opens the rewind UI
- [x] Single-press Esc still works as cancel in editor and input modes
- [x] Rewind UI has the same preview and restore options as `/restore`
- [x] Double-press does not trigger when Esc is held down
- [x] No regression in existing Esc behavior across all UI modes
- [x] Edge case: rapid triple-press handled as one double + one single

## Dependencies

Parent: [Epic 008](008-epic-checkpointing.md) — Checkpointing + Rewind

## Estimated Effort

~80 lines, 40 min
