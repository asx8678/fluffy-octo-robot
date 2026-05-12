---
id: "002-01"
title: "Git Status — Porcelain Parser & File State Counts"
status: closed
epic: "002"
labels: ["git", "status", "porcelain", "parser", "P1"]
created: "2025-07-14"
priority: "P1"
---

## Summary

Parse `git status` porcelain output to extract branch info, ahead/behind counts, and aggregate files by state (staged, unstaged, untracked, conflicted).

## Motivation

Raw `git status` is 20–50 lines for a typical repo. A compact summary like `main ↑2 ↓1 | staged: 3 | unstaged: 7 | untracked: 2` conveys the same information in one line.

## Deliverables

- Porcelain v1 parser (`git status --porcelain=v1`)
- Branch detection (`git branch`, `git status -b`, or rev-parse)
- Ahead/behind parsing
- File aggregation by two-letter status codes

## Acceptance Criteria

- [x] Correctly counts staged (`M`, `A`, `D` in first column)
- [x] Correctly counts unstaged (`M`, `D` in second column)
- [x] Correctly counts untracked (`??`)
- [x] Correctly counts conflicted (`UU`, `AA`, `DD`, etc.)
- [x] Shows branch name and ahead/behind if available
- [x] Falls back gracefully in detached HEAD state

## Dependencies

Parent: [Epic 002](002-epic-git-strategies.md) — Git Output Compression

## Estimated Effort

~120 lines, 1 hour
