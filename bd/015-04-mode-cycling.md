---
id: "015-04"
title: "Mode Cycling + /plan Command — Shift+Tab Cycle, /plan Shortcut"
status: closed
epic: "015"
labels: ["plan", "mode", "cycling", "keyboard", "command", "P2"]
created: "2025-07-14"
priority: "P2"
---

## Summary

Implement Shift+Tab keyboard shortcut to cycle through approval modes: default → auto-edit → plan → default. Display current mode indicator in UI. /plan [goal] slash command enters plan mode with optional goal text, skipping the manual cycling. Handle edge case: cycling during agent processing is ignored (don't interrupt active turn).

## Motivation

Quick mode switching without slash commands improves workflow fluidity. Keyboard shortcut matches Gemini CLI behavior.

## Deliverables

- Shift+Tab mode cycle handler
- Mode indicator in UI
- /plan command handler

## Acceptance Criteria

- [x] Shift+Tab cycles modes in order
- [x] mode indicator updates immediately
- [x] /plan "goal" enters plan mode with goal
- [x] cycling ignored during agent processing
- [x] plan mode clearly indicated in UI

## Dependencies

Parent: [Epic 015](015-epic-plan-mode.md), depends on 015-01

## Estimated Effort

~40 lines, 20 min
