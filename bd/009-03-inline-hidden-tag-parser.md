---
id: "009-03"
title: "InlineHiddenTagParser"
status: closed
epic: "009"
labels: ["stream", "parser", "inline", "tag", "hidden", "P0"]
created: "2025-07-14"
priority: "P0"
---

## Summary

Generic parser for hidden inline tags. Takes list of InlineTagSpec (tag identifier, open: str, close: str). Finds earliest open tag (longest match at same position). Extracts tag content while hiding tags from visible text. Auto-closes unterminated tags at finish(). Handles non-ASCII delimiters.

## Motivation

LLMs emit hidden inline tags (citations, plans) that must be extracted for processing but stripped from visible output. A generic parser supports any tag format without one-off implementations.

## Deliverables

- `InlineTagSpec` dataclass with tag identifier, open delimiter, close delimiter
- `InlineHiddenTagParser` that accepts a list of specs
- Earliest-open-tag matching with longest-match tiebreaker
- Tag content extracted into `extracted` list, tags removed from `visible_text`
- Auto-close of unterminated tags at `finish()`

## Acceptance Criteria

- [x] Earliest open tag found among all specs
- [x] Longest match wins when multiple tags start at the same position
- [x] Tag content extracted and stored with identifier
- [x] Open and close delimiters hidden from visible text
- [x] Unterminated tags auto-closed at `finish()` with full content extracted
- [x] Non-ASCII delimiters handled correctly
- [x] Nested tags of different types handled correctly

## Dependencies

Parent: [Epic 009](009-epic-stream-parser.md) — Stream Parser Framework

## Estimated Effort

~80 lines, 40 min
