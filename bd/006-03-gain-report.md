---
id: "006-03"
title: "rtk gain / rtk cc-economics Report Queries and Display"
status: closed
epic: "006"
labels: ["tracking", "report", "gain", "economics", "cli", "P3"]
created: "2025-07-14"
priority: "P3"
---

## Summary

Implement the `rtk gain` and `rtk cc-economics` commands that query the tracking database and display cumulative savings, top commands, and estimated dollar economics.

## Motivation

Users need feedback loops: seeing savings motivates adoption. Dollar estimates (even approximate) make the value concrete.

## Deliverables

- `gain` report: total tokens saved, commands filtered, top 5 strategies, daily trend
- `cc-economics`: approximate dollar savings using Claude Code token pricing
- Time-range filtering (today, week, month, all)
- Compact text output

## Acceptance Criteria

- [x] `gain` shows total raw vs compressed tokens
- [x] `gain` shows savings percentage
- [x] `gain` shows top 5 most-filtered commands
- [x] `cc-economics` shows estimated input and output token costs
- [x] `cc-economics` shows estimated dollar savings
- [x] Time range defaults to all-time, supports `--today`, `--week`, `--month`

## Dependencies

Parent: [Epic 006](006-epic-tracking.md) — Token Tracking Database
Depends on: [006-01](006-01-sqlite-schema.md), [006-02](006-02-tracking-insert.md)

## Estimated Effort

~100 lines, 1 hour
