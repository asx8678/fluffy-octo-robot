---
id: "004-01"
title: "Generic Lint Grouping — Parse by Rule/File, Count, Format"
status: closed
epic: "004"
labels: ["lint", "grouping", "ruff", "eslint", "tsc", "golangci-lint", "rubocop", "P2"]
created: "2025-07-14"
priority: "P2"
---

## Summary

Build a generic lint grounder that parses lint output by rule and file, counts occurrences, and presents a compact aggregated view.

## Motivation

Linters emit one line per violation. For large codebases, this is hundreds or thousands of repetitive lines. Grouping by rule then file reduces volume by 70–90% while preserving every actionable detail.

## Deliverables

- Rule extractor: parse rule ID from lint lines (language-specific)
- File grounder: group violations under each rule by file path
- Counter: tally occurrences per (rule, file)
- Formatter: compact text output

## Acceptance Criteria

- [x] Ruff: groups by rule code (E501, F401, etc.)
- [x] ESLint: groups by rule name (`no-unused-vars`, etc.)
- [x] TSC: groups by error code (TS2345, etc.)
- [x] Golangci-lint: groups by linter name + rule
- [x] Rubocop: groups by cop name
- [x] Each group shows rule, affected files, and violation counts
- [x] Supports `-v` to expand individual violations

## Dependencies

Parent: [Epic 004](004-epic-lint-strategies.md) — Lint Output Grouping

## Estimated Effort

~100 lines, 1 hour
