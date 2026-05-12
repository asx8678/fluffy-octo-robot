---
id: "002-02"
title: "Git Log — One-Line Format & Commit Stats"
status: closed
epic: "002"
labels: ["git", "log", "parser", "compression", "P1"]
created: "2025-07-14"
priority: "P1"
---

## Summary

Compress `git log` output into one-line per commit format with summary statistics: total commits, authors, files changed, insertions/deletions.

## Motivation

Full `git log` with diffs can be thousands of lines. Even default log output is verbose. One-line summaries with stats give the LLM context without drowning it.

## Deliverables

- One-line log formatter (`--oneline` style or custom)
- Commit count summary
- Optional stat aggregation (files changed, +/-)
- Author grouping for `-v` mode

## Acceptance Criteria

- [x] Default mode shows hash + subject for each commit
- [x] Summary line shows total commit count
- [x] `-v` mode includes author and date
- [x] `-vv` mode includes stat block (files changed, insertions, deletions)
- [x] Handles empty log gracefully
- [x] Works with `--all`, `--graph`, and branch args

## Dependencies

Parent: [Epic 002](002-epic-git-strategies.md) — Git Output Compression

## Estimated Effort

~80 lines, 45 minutes
