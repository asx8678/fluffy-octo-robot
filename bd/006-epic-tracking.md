---
id: "006"
title: "Epic: Token Tracking Database — SQLite History, Gain Reports, Economics"
status: closed
epic: "006"
labels: ["epic", "tracking", "sqlite", "analytics", "tokens", "economics", "P3"]
created: "2025-07-14"
priority: "P3"
---

## Summary

SQLite database for tracking input/output tokens per command, 90-day retention, and `rtk gain` / `rtk cc-economics` style reports.

## Motivation

Users need visibility into how much token volume Fast-Puppy is saving. A lightweight SQLite tracker enables per-command, per-session, and cumulative reporting without external services.

## Deliverables

1. SQLite schema + connection management + auto-cleanup
2. Track each command execution — insert input/output tokens, savings%
3. `rtk gain` / `rtk cc-economics` report queries and display
4. `rtk session` report — adoption across recent sessions

## Acceptance Criteria

- [x] Schema stores command, strategy, raw tokens, compressed tokens, timestamp
- [x] Auto-cleanup removes records older than 90 days
- [x] `gain` report shows total savings, top commands, and daily trend
- [x] `cc-economics` shows estimated dollar savings based on token pricing
- [x] `session` report shows adoption rate (% of commands filtered) per session
- [x] All reports output as compact text (not JSON) for LLM consumption

## Dependencies

Depends on [Epic 001](001-epic-filter-engine.md) — Core Filter Engine

## Estimated Effort

~350 lines, 3 hours

## Children

- [006-01](006-01-sqlite-schema.md) — SQLite schema
- [006-02](006-02-tracking-insert.md) — Tracking insert
- [006-03](006-03-gain-report.md) — Gain report
- [006-04](006-04-session-report.md) — Session report
