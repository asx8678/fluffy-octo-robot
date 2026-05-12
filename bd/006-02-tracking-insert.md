---
id: "006-02"
title: "Track Each Command Execution — Insert Tokens & Savings"
status: closed
epic: "006"
labels: ["tracking", "sqlite", "insert", "metrics", "P3"]
created: "2025-07-14"
priority: "P3"
---

## Summary

Instrument the dispatcher to record every command execution: input tokens (raw output size), output tokens (compressed size), strategy used, and computed savings percentage.

## Motivation

Without per-command tracking, the gain and session reports have no data. This issue wires the database into the filtering pipeline.

## Deliverables

- Hook into dispatcher post-strategy execution
- Count tokens (approximate via whitespace-split or tiktoken-lite)
- Compute savings % = (raw - compressed) / raw
- Insert record into SQLite

## Acceptance Criteria

- [x] Every filtered command produces a tracking record
- [x] Raw and compressed token counts are stored
- [x] Savings percentage is computed and stored
- [x] Session ID is consistent across a single agent session
- [x] Passthrough commands are also tracked (with 0% savings)
- [x] Insert is non-blocking and wrapped in try/except

## Dependencies

Parent: [Epic 006](006-epic-tracking.md) — Token Tracking Database
Depends on: [006-01](006-01-sqlite-schema.md), [001-03](001-03-dispatcher.md)

## Estimated Effort

~80 lines, 45 minutes
