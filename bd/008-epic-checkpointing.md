---
id: "008"
title: "Epic: Checkpointing + Rewind — Shadow Git, Conversation Snapshots, Interactive Undo"
status: closed
epic: "008"
labels: ["epic", "checkpointing", "rewind", "undo", "git", "snapshot", "P0"]
created: "2025-07-14"
priority: "P0"
---

## Summary

Port Gemini CLI's checkpointing and rewind system. Auto-create shadow git commits + conversation snapshots before every file-modifying tool. `/restore` slash command with interactive rewind UI (list checkpoints, preview, select revert scope).

## Motivation

Muse has no undo beyond single file revert. Gemini's automatic checkpointing is the most polished undo system across all analyzed projects.

## Deliverables

1. Shadow git repo in `~/.muse/history/<project_hash>/`
2. Conversation snapshot JSON (messages + tool calls)
3. Checkpoint creation hook in pre-tool-use callback
4. `/restore` slash command with interactive TUI
5. Rewind keyboard shortcut (Esc×2)

## Acceptance Criteria

- [x] Checkpoint auto-created before `write_file` and `replace_in_file` tool calls
- [x] `/restore` lists checkpoints with timestamp, tool name, and affected files
- [x] Restore reverts both files and conversation state to the selected checkpoint
- [x] Esc×2 opens the rewind UI from any mode
- [x] Rewind works across conversation compaction boundaries
- [x] Shadow git repository does not interfere with the user's own git repository

## Dependencies

None. Standalone.

## Estimated Effort

~500 lines, 4 hours

## Children

- [008-01](008-01-shadow-git.md) — Shadow Git Repository (shadow git init, commit on checkpoint, ~/.muse/history/)
- [008-02](008-02-conversation-snapshots.md) — Conversation Snapshots (JSON snapshot of messages + pending tool calls)
- [008-03](008-03-checkpoint-hook.md) — Checkpoint Hook Integration (pre-tool-use callback, auto-create before file mutations)
- [008-04](008-04-restore-command.md) — /restore Slash Command (list, preview, select scope — conversation+files, conversation only, files only)
- [008-05](008-05-rewind-shortcut.md) — Rewind Keyboard Shortcut (Esc×2, interactive TUI, same restore options)
