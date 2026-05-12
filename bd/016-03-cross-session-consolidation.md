---
id: "016-03"
title: "Phase 2 — Cross-Session Consolidation into MEMORY.md + Skills"
status: "open"
epic: "016"
labels: ["memory", "consolidation", "synthesis", "MEMORY.md", "P3"]
created: "2025-07-14"
priority: "P3"
---

## Summary

After per-session extraction, run a second consolidation pass using a consolidation model role. This agent reads all raw_memory blocks and synopses, then produces three outputs: MEMORY.md (curated long-term knowledge document with sections like Conventions, Gotchas, Decisions), memory_summary.md (compact version injected at session start, <500 words), and skills/ directory (reusable procedural playbooks extracted from repeated workflows). Handles empty extraction set (writes nothing).

## Motivation

Individual session extractions are noisy. Consolidation synthesizes them into coherent, deduplicated, actionable knowledge.

## Deliverables

- `consolidate_memories(extractions: list[ExtractionResult], project_dir: Path) → ConsolidationResult`
- Outputs: MEMORY.md path, memory_summary.md path, list of generated skill paths

## Acceptance Criteria

- [x] MEMORY.md has clear sections
- [x] memory_summary.md under 500 words
- [x] duplicate knowledge merged
- [x] skills generated for repeated patterns
- [x] handles empty extractions
- [x] consolidation prompt uses templates from docs

## Dependencies

Parent [Epic 016](016-epic-autonomous-memory.md), depends on 016-02.

## Estimated Effort

~120 lines, 1 hour.
