---
id: "004-02"
title: "Grep/Find Grouping — Group Results by File/Directory"
status: closed
epic: "004"
labels: ["lint", "grep", "find", "grouping", "search", "P2"]
created: "2025-07-14"
priority: "P2"
---

## Summary

Group `grep` and `find` output by file or directory, compressing scattered line matches into per-file summaries.

## Motivation

`grep -r` across a codebase produces one line per match, often with long paths. Grouping by file lets the LLM see "file X has matches at lines 10, 25, 42" instead of 3 nearly identical lines.

## Deliverables

- Grep parser: extract file path, line number, and matched text
- File grounder: collect all matches per file
- Find parser: group by directory with file counts
- Compact formatter

## Acceptance Criteria

- [x] Grep output groups by file with line-number lists
- [x] Match text is preserved (not truncated unless very long)
- [x] Find output groups by directory with file counts
- [x] Supports `grep -n`, `grep -H`, and `grep -r` variants
- [x] Handles binary file match warnings gracefully

## Dependencies

Parent: [Epic 004](004-epic-lint-strategies.md) — Lint Output Grouping

## Estimated Effort

~80 lines, 45 minutes
