---
id: "005-04"
title: "Log Deduplication — Collapse Repeated Lines with Counts"
status: closed
epic: "005"
labels: ["code", "log", "dedup", "deduplication", "compression", "P2"]
created: "2025-07-14"
priority: "P2"
---

## Summary

Collapse consecutive repeated lines in log-like output into a single line with a `× N` count annotation.

## Motivation

Logs often contain thousands of identical lines (e.g., "Retrying...", "Polling..."). Deduplication preserves the information (it happened N times) while cutting volume drastically.

## Deliverables

- Run-length encoder for text lines
- `× N` suffix formatter
- Threshold: collapse only when N ≥ 3 (configurable)
- Optional: collapse near-identical lines with fuzzy matching

## Acceptance Criteria

- [x] Identical consecutive lines collapse to one line + count
- [x] Count shown as `× N` suffix
- [x] Non-consecutive duplicates are not collapsed
- [x] Threshold of 3 consecutive lines before collapsing
- [x] Works on both stdout and stderr
- [x] Preserves line ordering outside of collapsed runs

## Dependencies

Parent: [Epic 005](005-epic-code-strategies.md) — Code-Aware Filtering

## Estimated Effort

~70 lines, 45 minutes
