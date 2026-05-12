---
id: "013-04"
title: "Slash Commands for Management — /commands list + /commands reload"
status: closed
epic: "013"
labels: ["commands", "slash", "management", "list", "reload", "P2"]
created: "2025-07-14"
priority: "P2"
---

## Summary

Implement /commands list (show all available custom commands with namespace, description, and source tier) and /commands reload (rescan command directories and update registry without restarting the session). Handle edge cases: no commands defined, invalid files in directories, reload while commands are in use.

## Motivation

Users need visibility into what commands are available and a way to pick up changes without restarting the agent. Compact, LLM-readable output keeps the context window clean.

## Deliverables

- `/commands list` handler (formatted table output)
- `/commands reload` handler (rescan + update registry atomically)

## Acceptance Criteria

- [x] List shows namespace:name, description, source
- [x] Reload picks up new files
- [x] Reload handles deleted files (removes from registry)
- [x] Reload preserves built-in commands
- [x] Output is compact (LLM-readable)

## Dependencies

Parent: [Epic 013](013-epic-custom-commands.md) — Custom Commands. Depends on [013-02](013-02-command-discovery.md).

## Estimated Effort

~50 lines, 25 min
