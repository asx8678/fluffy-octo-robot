---
id: "008-04"
title: "/restore Slash Command"
status: closed
epic: "008"
labels: ["checkpointing", "restore", "slash-command", "tui", "P0"]
created: "2025-07-14"
priority: "P0"
---

## Summary

List available checkpoints (timestamp, tool, affected files). Preview selected checkpoint (show diff of file changes, conversation summary). Three restore scopes: conversation+files (full revert), conversation only, files only. Confirm dialog before execution. Handle edge case: no checkpoints exist.

## Motivation

Users need a discoverable, safe way to rewind mistakes. A slash command with preview and confirmation prevents accidental reverts and makes checkpoint browsing intuitive.

## Deliverables

- `/restore` slash command with checkpoint listing UI
- Checkpoint preview: diff of file changes + conversation summary
- Three restore scopes: full, conversation-only, files-only
- Confirmation dialog before executing any restore

## Acceptance Criteria

- [x] `/restore` lists all available checkpoints with timestamp, tool, and affected files
- [x] Preview shows a readable diff and conversation summary for the selected checkpoint
- [x] Full restore reverts both conversation and files
- [x] Conversation-only restore reverts messages and agent state, not files
- [x] Files-only restore reverts files, not conversation state
- [x] Confirmation dialog prevents accidental restores
- [x] Graceful message when no checkpoints exist

## Dependencies

Parent: [Epic 008](008-epic-checkpointing.md) — Checkpointing + Rewind

## Estimated Effort

~120 lines, 1 hour
