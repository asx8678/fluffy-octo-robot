---
id: "002"
title: "Epic: Git Output Compression — Status/Log/Diff/Add/Commit/Push"
status: closed
epic: "002"
labels: ["epic", "git", "compression", "P1", "porcelain", "status", "log", "diff"]
created: "2025-07-14"
priority: "P1"
---

## Summary

Port RTK's git porcelain parsers to Fast-Puppy. Compress `git status`, `git log`, `git diff`, and mutation commands (add/commit/push/pull) into minimal, high-signal output.

## Motivation

Git commands are among the most frequent shell invocations in agent workflows. Raw git output is extremely verbose. RTK proved that git porcelain can be compressed by 80–95% without losing semantic value.

## Deliverables

1. `git status` — parse porcelain, extract branch info, count files by state
2. `git log` — one-line format, count commits, extract stats
3. `git diff` — `--stat` mode only, compact diff
4. `git add`/`commit`/`push`/`pull` → "ok" / "ok abc1234" responses

## Acceptance Criteria

- [x] `git status` output shows branch, ahead/behind, and file counts by state
- [x] `git log` shows one-line summaries with commit counts
- [x] `git diff` defaults to `--stat`; full diff available via `-v`
- [x] Mutation commands return minimal success confirmations
- [x] All parsers handle edge cases: empty repos, detached HEAD, merge conflicts

## Dependencies

Depends on [Epic 001](001-epic-filter-engine.md) — Core Filter Engine

## Estimated Effort

~350 lines, 3 hours

## Children

- [002-01](002-01-git-status.md) — Git status parser
- [002-02](002-02-git-log.md) — Git log parser
- [002-03](002-03-git-diff.md) — Git diff parser
- [002-04](002-04-git-mutations.md) — Git mutation commands
