---
id: "016-02"
title: "Phase 1 — Per-Session Knowledge Extraction via Background Agent"
status: "open"
epic: "016"
labels: ["memory", "extraction", "session", "background", "P3"]
created: "2025-07-14"
priority: "P3"
---

## Summary

For each eligible session, run a background extraction agent (headless, using smol model role). The agent reads the full session transcript and extracts durable knowledge: technical decisions made, constraints discovered, recurring workflows, pitfalls encountered, project-specific conventions. Produces a raw_memory block (markdown text) and a short synopsis (one-line summary). Runs as non-blocking background task.

## Motivation

Session transcripts contain valuable tacit knowledge. Extracting it automatically builds institutional memory without manual effort.

## Deliverables

- `extract_session_knowledge(session_path: Path) → ExtractionResult`
- `ExtractionResult` with raw_memory: str, synopsis: str, extracted_at: datetime
- Background task management (asyncio.create_task, timeout)

## Acceptance Criteria

- [x] extraction runs without blocking UI
- [x] raw_memory captures technical decisions
- [x] synopsis is concise one-liner
- [x] handles empty sessions gracefully
- [x] timeout prevents hung extractions
- [x] errors logged not fatal

## Dependencies

Parent [Epic 016](016-epic-autonomous-memory.md), depends on 016-01.

## Estimated Effort

~120 lines, 1 hour.
