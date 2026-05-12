---
id: "005"
title: "Epic: Code-Aware Filtering — Read/Smart/Ls/Tree"
status: closed
epic: "005"
labels: ["epic", "code", "filter", "truncate", "tree", "ls", "P2"]
created: "2025-07-14"
priority: "P2"
---

## Summary

Language-aware comment stripping, directory tree compression, and smart truncation for file-reading commands. Port RTK's `MinimalFilter` and `AggressiveFilter` concepts.

## Motivation

When agents read source files, they often ingest huge comment blocks, docstrings, and boilerplate. Code-aware filtering strips noise while preserving semantics, cutting read tokens by 40–60%.

## Deliverables

1. `MinimalFilter` and `AggressiveFilter` — language-aware comment stripping for 9+ languages
2. Directory tree — convert flat `ls` to hierarchy with counts
3. `smart_truncate` — keep important lines, skip noise
4. Log deduplication — collapse repeated lines with counts

## Acceptance Criteria

- [x] Python: strips `#` comments and docstrings in aggressive mode
- [x] JavaScript/TypeScript: strips `//`, `/* */`, and JSDoc
- [x] Rust/Go/Java/C/C++/Ruby/Bash: language-appropriate comment stripping
- [x] `ls -R` / `tree` output compressed to hierarchical summary
- [x] `smart_truncate` preserves imports, signatures, and error-adjacent lines
- [x] Log dedup collapses identical consecutive lines with `× N` notation

## Dependencies

Depends on [Epic 001](001-epic-filter-engine.md) — Core Filter Engine

## Estimated Effort

~400 lines, 4 hours

## Children

- [005-01](005-01-code-filter.md) — Minimal/AggressiveFilter
- [005-02](005-02-tree-compression.md) — Tree compression
- [005-03](005-03-read-truncate.md) — smart_truncate
- [005-04](005-04-dedup-log.md) — Log deduplication
