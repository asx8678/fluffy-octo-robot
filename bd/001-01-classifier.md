---
id: "001-01"
title: "Build Command Classifier with Regex Pattern Matching"
status: closed
epic: "001"
labels: ["filter-engine", "classifier", "regex", "core", "P0"]
created: "2025-07-14"
priority: "P0"
---

## Summary

Build the command classifier that maps shell commands to strategy categories by porting RTK's REGEX_SET approach.

## Motivation

The classifier is the entry point of the filter engine. It must be fast, accurate, and extensible. Regex patterns are the proven RTK approach for lightweight command classification.

## Deliverables

- Regex pattern set for git, test, lint, code, and unknown categories
- Category enum or constant mapping
- Unit tests for edge cases (aliases, flags, paths)

## Acceptance Criteria

- [x] `git status` → category `git`
- [x] `pytest tests/` → category `test`
- [x] `ruff check .` → category `lint`
- [x] `cat file.py` → category `code` (or `read`)
- [x] Unmatched commands → category `unknown` (passthrough)
- [x] Patterns handle flags, paths, and subcommands correctly

## Dependencies

Parent: [Epic 001](001-epic-filter-engine.md) — Core Filter Engine

## Estimated Effort

~120 lines, 1 hour
