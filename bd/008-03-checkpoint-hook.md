---
id: "008-03"
title: "Checkpoint Hook Integration"
status: closed
epic: "008"
labels: ["checkpointing", "hook", "pre-tool-use", "integration", "P0"]
created: "2025-07-14"
priority: "P0"
---

## Summary

Wire checkpoint creation into pre-tool-use callback in the Claude Code hooks plugin. Only trigger for file-modifying tools (write_file, replace_in_file). Must not block tool execution — fire-and-forget with error logging. Coordinate with shadow git and snapshot systems.

## Motivation

Checkpoints must be automatic and invisible to the user. A non-blocking hook guarantees every file-modifying tool is backed by a recoverable state without adding latency to the tool execution path.

## Deliverables

- Pre-tool-use hook that detects file-modifying tool calls
- Fire-and-forget checkpoint trigger (async or background thread)
- Error logging if checkpoint fails (never blocks tool execution)
- Coordination with shadow git and snapshot subsystems

## Acceptance Criteria

- [x] Hook fires only for write_file and replace_in_file tool calls
- [x] Tool execution is never blocked by checkpoint creation
- [x] Failed checkpoints are logged, not raised
- [x] Shadow git commit and snapshot created in the same logical checkpoint
- [x] Hook registered in the Claude Code hooks plugin correctly
- [x] Duplicate checkpoints for the same tool call deduplicated

## Dependencies

Parent: [Epic 008](008-epic-checkpointing.md) — Checkpointing + Rewind

## Estimated Effort

~100 lines, 45 min
