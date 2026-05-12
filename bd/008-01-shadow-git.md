---
id: "008-01"
title: "Shadow Git Repository — Auto-Commit on File-Modifying Tools"
status: closed
epic: "008"
labels: ["checkpointing", "git", "shadow", "commit", "P0"]
created: "2025-07-14"
priority: "P0"
---

## Summary

Initialize a bare git repo in `~/.muse/history/<project_hash>/`. Before every write_file or replace_in_file tool call, auto-commit the full project tree with `git add -A && git commit --allow-empty -m "checkpoint: <tool_name> <timestamp>"`. Use `git -C <project_root>` to operate on the user's repo without interfering with their own git state. Handle edge cases: large repos (commit may be slow but acceptable), concurrent commits (git handles this natively), empty repo (use --allow-empty).

## Motivation

We need a fully automatic, invisible checkpointing system that captures the entire project state before any file mutation. A shadow git repo gives us atomic snapshots, cheap storage via delta compression, and native rewind via `git checkout` — all without touching the user's own git history.

## Deliverables

- ShadowGit class with `init_shadow_git(project_root)` → repo_path
- `create_checkpoint(tool_name, affected_files)` → commit_hash
- Path resolution using project hash (SHA-256 of cwd)
- Auto-init on first checkpoint

## Acceptance Criteria

- [x] repo created at correct path (`~/.muse/history/<project_hash>/`)
- [x] commit includes all tracked files (via `git add -A`)
- [x] commit message includes tool name and ISO timestamp
- [x] shadow git path not inside user's repo
- [x] works on first call and subsequent calls
- [x] errors logged not raised

## Dependencies

Parent: [Epic 008](008-epic-checkpointing.md) — Checkpointing + Rewind

## Estimated Effort

~100 lines, 45 min
