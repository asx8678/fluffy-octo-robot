---
id: "007-01"
title: "Tee Mode — Save Raw Output on Failure, Hint Path to LLM"
status: closed
epic: "007"
labels: ["integration", "tee", "recovery", "failure", "P3"]
created: "2025-07-14"
priority: "P3"
---

## Summary

Implement tee recovery: when a filter strategy crashes or produces suspicious output, save the raw command output to a temp file and return a hint message pointing the LLM to the full output.

## Motivation

Filter bugs must never lose user data. Tee mode guarantees the raw output is recoverable, making the filter engine safe to deploy aggressively.

## Deliverables

- Temp file writer: save raw stdout/stderr to `/tmp/rtk-puppy/...`
- Hint formatter: `⚠ filter error — raw output saved to <path>`
- Cleanup: old tee files purged after 24 hours
- Configurable: tee always, tee on error, or tee never

## Acceptance Criteria

- [x] On strategy exception, raw output is written to a temp file
- [x] Returned message includes the temp file path
- [x] Temp files are namespaced by session and timestamp
- [x] Auto-cleanup removes tee files older than 24 hours
- [x] Tee-on-error is the default mode
- [x] Tee files are readable by the owning user only (0600)

## Dependencies

Parent: [Epic 007](007-epic-integration.md) — Integration & Polish
Depends on: [001-03](001-03-dispatcher.md)

## Estimated Effort

~80 lines, 1 hour
