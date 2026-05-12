---
id: "004-03"
title: "JSON/Text Dual Mode — Inject --format=json for Ruff/Golangci/Pip"
status: closed
epic: "004"
labels: ["lint", "json", "dual-mode", "ruff", "golangci-lint", "pip", "P2"]
created: "2025-07-14"
priority: "P2"
---

## Summary

When available, inject `--format=json` (or equivalent) to get structured lint output, which is easier to parse and more reliable than regex scraping.

## Motivation

Text parsing is brittle. JSON output is stable and machine-readable. Many modern tools (ruff, golangci-lint, pip) support JSON formatting. Using it when available reduces parser maintenance.

## Deliverables

- Detect JSON support per tool
- Inject `--format=json` or equivalent flag
- JSON parser for each supported tool
- Fallback to text parser if JSON fails or is unsupported

## Acceptance Criteria

- [x] Ruff: uses `--output-format=json` when available
- [x] Golangci-lint: uses `--out-format=json` when available
- [x] Pip: parses JSON output from compatible subcommands
- [x] Fallback to text parser is transparent and automatic
- [x] JSON parse errors do not crash the filter engine

## Dependencies

Parent: [Epic 004](004-epic-lint-strategies.md) — Lint Output Grouping

## Estimated Effort

~70 lines, 45 minutes
