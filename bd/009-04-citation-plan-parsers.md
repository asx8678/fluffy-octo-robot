---
id: "009-04"
title: "Citation + Plan Parsers"
status: closed
epic: "009"
labels: ["stream", "parser", "citation", "plan", "assistant", "P0"]
created: "2025-07-14"
priority: "P0"
---

## Summary

CitationStreamParser: thin wrapper around InlineHiddenTagParser for <oai-mem-citation> tags. strip_citations(text) one-shot helper. ProposedPlanParser: wraps TaggedLineParser for <proposed_plan> blocks. Emits ProposedPlanSegment enum (Normal, PlanStart, PlanDelta, PlanEnd). AssistantTextStreamParser: combines citation + plan in one pass with plan_mode flag. extract_proposed_plan_text() helper.

## Motivation

These are the concrete parsers the assistant uses: citations for memory references, proposed plans for plan mode, and a combined parser that drives the main text stream. Thin wrappers keep the core generic parser reusable.

## Deliverables

- `CitationStreamParser` wrapping `InlineHiddenTagParser` for `<oai-mem-citation>`
- `strip_citations(text)` one-shot helper function
- `ProposedPlanParser` wrapping `TaggedLineParser` for `<proposed_plan>` blocks
- `ProposedPlanSegment` enum: Normal, PlanStart, PlanDelta, PlanEnd
- `AssistantTextStreamParser` combining citation + plan in one pass
- `extract_proposed_plan_text()` helper

## Acceptance Criteria

- [x] `CitationStreamParser` extracts citation tags and hides them from visible text
- [x] `strip_citations(text)` returns text with all citation tags removed
- [x] `ProposedPlanParser` emits correct segment enum values
- [x] `AssistantTextStreamParser` handles both citations and plans in one pass
- [x] `plan_mode` flag controls whether plan segments are emitted or ignored
- [x] `extract_proposed_plan_text()` returns raw plan text from segments
- [x] All parsers compose correctly with the base `StreamTextParser` interface

## Dependencies

Parent: [Epic 009](009-epic-stream-parser.md) — Stream Parser Framework

## Estimated Effort

~60 lines, 30 min
