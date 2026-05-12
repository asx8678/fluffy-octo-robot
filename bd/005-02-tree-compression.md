---
id: "005-02"
title: "Directory Tree — Convert Flat ls to Hierarchy with Counts"
status: closed
epic: "005"
labels: ["code", "tree", "ls", "directory", "compression", "P2"]
created: "2025-07-14"
priority: "P2"
---

## Summary

Compress flat `ls` or `tree` output into a hierarchical directory summary with file counts per directory.

## Motivation

`ls -R` on a large project emits hundreds of lines. A tree view with counts like `src/components/  (12 files)` gives the LLM structural context in a fraction of the tokens.

## Deliverables

- `ls -R` parser: extract paths and file names
- Directory tree builder: aggregate into hierarchy
- Count aggregator: files per directory
- Compact formatter with depth limit

## Acceptance Criteria

- [x] Flat `ls` output is converted to indented tree
- [x] Each directory shows immediate file count
- [x] Recursive directories shown with nesting
- [x] Depth limit truncates deep trees with `...` indicator
- [x] Hidden files optionally included/excluded
- [x] Symbolic links noted but not followed

## Dependencies

Parent: [Epic 005](005-epic-code-strategies.md) — Code-Aware Filtering

## Estimated Effort

~100 lines, 1 hour
