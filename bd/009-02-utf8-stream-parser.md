---
id: "009-02"
title: "Utf8StreamParser"
status: closed
epic: "009"
labels: ["stream", "parser", "utf8", "bytes", "P0"]
created: "2025-07-14"
priority: "P0"
---

## Summary

Adapter that wraps any StreamTextParser and accepts raw bytes. Buffers partial UTF-8 code points across chunk boundaries. On invalid UTF-8, rolls back entire chunk (no partial state corruption). finish() flushes buffer. into_inner() returns wrapped parser if no pending bytes. into_inner_lossy() drops pending bytes.

## Motivation

Network streams deliver raw bytes, but our parser framework works on strings. A UTF-8 adapter bridges this gap safely, handling split code points and invalid byte sequences without corrupting parser state.

## Deliverables

- `Utf8StreamParser` adapter wrapping any `StreamTextParser`
- Raw bytes input interface (`push_bytes` or equivalent)
- Partial UTF-8 code point buffering across chunk boundaries
- Invalid UTF-8 rollback: entire chunk rejected, no parser state corruption
- `finish()` flushes any pending bytes
- `into_inner()` and `into_inner_lossy()` accessors

## Acceptance Criteria

- [x] Accepts raw bytes and converts to str for the inner parser
- [x] Partial UTF-8 code points buffered until complete
- [x] Invalid UTF-8 causes entire chunk rollback, inner parser untouched
- [x] `finish()` flushes and processes any remaining buffered bytes
- [x] `into_inner()` returns inner parser only if no pending bytes
- [x] `into_inner_lossy()` returns inner parser and drops pending bytes
- [x] Multi-byte UTF-8 sequences split across 2+ chunks handled correctly

## Dependencies

Parent: [Epic 009](009-epic-stream-parser.md) — Stream Parser Framework

## Estimated Effort

~100 lines, 45 min
