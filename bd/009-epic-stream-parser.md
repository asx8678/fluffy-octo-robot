---
id: "009"
title: "Epic: Stream Parser Framework — UTF-8 Safe, Citation/Plan Extraction, Generic Tag Parsing"
status: closed
epic: "009"
labels: ["epic", "stream", "parser", "utf8", "citation", "plan", "P0"]
created: "2025-07-14"
priority: "P0"
---

## Summary

Port Codex's `utils/stream-parser` crate to Python. Composable streaming text parsers: Utf8StreamParser (raw bytes → UTF-8 safe chunks), InlineHiddenTagParser (generic hidden tag extraction), CitationStreamParser, ProposedPlanParser.

## Motivation

Muse uses Termflow for markdown but has no structured way to handle model output markup (citations, plan blocks, hidden tags) that may be split across SSE chunk boundaries. Codex's framework is the most complete implementation.

## Deliverables

1. StreamTextParser abstract base + StreamTextChunk dataclass
2. Utf8StreamParser (raw bytes, partial UTF-8 buffering, rollback on invalid)
3. InlineHiddenTagParser<T> (generic open/close tag extraction)
4. CitationStreamParser (`<oai-mem-citation>`)
5. ProposedPlanParser (`<proposed_plan>` blocks for plan mode)
6. AssistantTextStreamParser (combines citation + plan in one pass)

## Acceptance Criteria

- [x] Parsers produce correct output across arbitrary chunk boundaries
- [x] UTF-8 code points split across chunks are handled correctly with buffering
- [x] Invalid UTF-8 triggers rollback rather than crash
- [x] Citations extracted as strings with full tag content
- [x] Plan segments extracted with Normal/Start/Delta/End chunk types
- [x] All parsers are composable (e.g., wrap CitationStreamParser in Utf8StreamParser)

## Dependencies

None. Standalone utility.

## Estimated Effort

~300 lines, 2.5 hours

## Children

- [009-01](009-01-stream-text-parser.md) — StreamTextParser Base + StreamTextChunk (abstract class, dataclass, default/empty)
- [009-02](009-02-utf8-stream-parser.md) — Utf8StreamParser (raw bytes adapter, partial UTF-8 buffering, finish/into_inner)
- [009-03](009-03-inline-hidden-tag-parser.md) — InlineHiddenTagParser (generic open/close tag extraction, longest-match preference)
- [009-04](009-04-citation-plan-parsers.md) — Citation + Plan Parsers (CitationStreamParser, ProposedPlanParser, AssistantTextStreamParser combo)
