---
id: "004"
title: "Epic: Lint Output Grouping — Ruff/Eslint/Tsc/Golangci/Rubocop"
status: closed
epic: "004"
labels: ["epic", "lint", "grouping", "ruff", "eslint", "tsc", "golangci-lint", "rubocop", "P2"]
created: "2025-07-14"
priority: "P2"
---

## Summary

Group lint errors by rule and file, count occurrences, and present compact aggregated views. Also handle grep/find grouping.

## Motivation

Lint output is repetitive: the same rule violated across many files. RTK's grouping approach shows "rule X → 12 files → 34 occurrences" instead of 34 nearly identical lines. This saves tokens and improves readability.

## Deliverables

1. Generic lint grouping — parse by rule/file, count, format
2. Grep/find grouping — group results by file/directory
3. JSON/text dual mode — inject `--format=json` for ruff/golangci/pip when beneficial

## Acceptance Criteria

- [x] Ruff output groups by rule code (e.g., E501 → 5 files)
- [x] ESLint/TSC groups by rule/message type
- [x] Golangci-lint supports both JSON and text grouping
- [x] Grep results group by file with line-number lists
- [x] Find results group by directory with file counts
- [x] JSON dual mode correctly falls back to text if JSON unavailable

## Dependencies

Depends on [Epic 001](001-epic-filter-engine.md) — Core Filter Engine

## Estimated Effort

~250 lines, 2 hours

## Children

- [004-01](004-01-lint-grouping.md) — Generic lint grouping
- [004-02](004-02-grep-find.md) — Grep/find grouping
- [004-03](004-03-json-dual.md) — JSON/text dual mode
