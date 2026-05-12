---
id: "002-03"
title: "Git Diff — Stat-Only Mode & Compact Diff"
status: closed
epic: "002"
labels: ["git", "diff", "stat", "parser", "compression", "P1"]
created: "2025-07-14"
priority: "P1"
---

## Summary

Default `git diff` to `--stat` mode for minimal output, with `-v` escalating to patch view. Parse stat lines into compact file summaries.

## Motivation

Patch diffs are the most token-expensive output in git. In most agent workflows, the agent only needs to know *which* files changed and roughly how much. Stat mode provides exactly that.

## Deliverables

- Stat parser: file name, insertions, deletions, net change
- Default strategy replaces `git diff` with `git diff --stat`
- `-v` flag allows patch output
- Binary file detection

## Acceptance Criteria

- [x] Default output shows files changed with +/- counts
- [x] Binary files noted without diff content
- [x] `-v` shows first N lines of patch, then truncates
- [x] `-vv` shows full patch
- [x] Handles empty diff gracefully

## Dependencies

Parent: [Epic 002](002-epic-git-strategies.md) — Git Output Compression

## Estimated Effort

~80 lines, 45 minutes
