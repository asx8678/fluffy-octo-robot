---
id: "009-01"
title: "StreamTextParser Base + StreamTextChunk"
status: closed
epic: "009"
labels: ["stream", "parser", "base", "dataclass", "P0"]
created: "2025-07-14"
priority: "P0"
---

## Summary

Abstract base class with push_str(chunk: str) -> StreamTextChunk and finish() -> StreamTextChunk methods. StreamTextChunk dataclass with visible_text: str and extracted: list[T] fields. Default/empty constructors. Composeable design — parsers wrap other parsers.

## Motivation

Streaming LLM responses need incremental parsing for hidden tags, citations, and plans. A composable parser framework lets us layer parsers without re-implementing buffering logic each time.

## Deliverables

- `StreamTextChunk` dataclass with `visible_text` and `extracted` fields
- `StreamTextParser` abstract base class
- `push_str(chunk: str) -> StreamTextChunk` method
- `finish() -> StreamTextChunk` method
- Composeable wrapper design (one parser can wrap another)

## Acceptance Criteria

- [x] `StreamTextChunk` has `visible_text: str` and `extracted: list[T]`
- [x] Base class defines `push_str` and `finish` with correct signatures
- [x] Default/empty constructors exist for all types
- [x] Parser composition works: wrapping parser delegates and merges output
- [x] No data loss when chunks split inside tag boundaries
- [x] Finish flushes any internal state correctly

## Dependencies

Parent: [Epic 009](009-epic-stream-parser.md) — Stream Parser Framework

## Estimated Effort

~60 lines, 30 min
