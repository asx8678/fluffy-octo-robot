---
id: "005-03"
title: "smart_truncate — Keep Important Lines, Skip Noise"
status: closed
epic: "005"
labels: ["code", "truncate", "smart", "read", "P2"]
created: "2025-07-14"
priority: "P2"
---

## Summary

Implement `smart_truncate` for file-reading commands: intelligently preserve imports/signatures and skip filler lines when output exceeds a token budget.

## Motivation

When an agent reads a large file, it often only needs the imports, class/function signatures, and lines near errors. `smart_truncate` keeps structural lines and removes middle noise.

## Deliverables

- Heuristic line importance scorer
- Keep: imports, definitions, decorators, docstring first line
- Skip: long runs of simple statements, blank lines, obvious filler
- Configurable token/line budget
- Ellipsis insertion where truncated

## Acceptance Criteria

- [x] Preserves all import/include lines at top of file
- [x] Preserves all class/function/struct definitions
- [x] Preserves lines adjacent to error markers (if provided)
- [x] Removes long runs of assignment/call lines
- [x] Inserts `[... N lines omitted ...]` where cut
- [x] Respects a configurable max-line budget

## Dependencies

Parent: [Epic 005](005-epic-code-strategies.md) — Code-Aware Filtering

## Estimated Effort

~80 lines, 1 hour
