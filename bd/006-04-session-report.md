---
id: "006-04"
title: "rtk session Report — Adoption Across Recent Sessions"
status: closed
epic: "006"
labels: ["tracking", "report", "session", "adoption", "cli", "P3"]
created: "2025-07-14"
priority: "P3"
---

## Summary

Implement the `rtk session` report that shows filtering adoption rates across recent sessions: what percentage of commands were filtered vs passthrough.

## Motivation

Session-level metrics help users (and developers) understand how well the filter engine is covering their workflow. Low adoption means missing strategies.

## Deliverables

- Query sessions by session ID, ordered by recency
- Compute adoption rate per session: filtered / total commands
- Show session duration (first → last command timestamp)
- Highlight sessions with 0% adoption (potential gaps)

## Acceptance Criteria

- [x] Shows last 10 sessions by default
- [x] Each session shows total commands, filtered count, adoption %
- [x] Sessions with <50% adoption are flagged
- [x] Average adoption rate across all sessions is shown
- [x] Compact text table format

## Dependencies

Parent: [Epic 006](006-epic-tracking.md) — Token Tracking Database
Depends on: [006-01](006-01-sqlite-schema.md), [006-02](006-02-tracking-insert.md)

## Estimated Effort

~70 lines, 45 minutes
