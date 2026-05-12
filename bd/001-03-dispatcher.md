---
id: "001-03"
title: "Filter Dispatcher — Capture, Apply, Return"
status: closed
epic: "001"
labels: ["filter-engine", "dispatcher", "capture", "core", "P0"]
created: "2025-07-14"
priority: "P0"
---

## Summary

Build the filter dispatcher that executes the underlying shell command, captures stdout/stderr, applies the matched strategy, and returns the compact result.

## Motivation

The dispatcher is the orchestration layer. It must be reliable, handle errors gracefully, and preserve the original command semantics while substituting output.

## Deliverables

- Command execution wrapper (subprocess or hook interception)
- Output capture (stdout + stderr)
- Strategy application pipeline
- Error handling and fallback to raw output

## Acceptance Criteria

- [x] Dispatcher runs the original command unchanged
- [x] Captures both stdout and stderr
- [x] Applies the strategy registered for the command's category
- [x] On strategy exception, falls back to raw output + logs error
- [x] Respects timeout and encoding settings
- [x] Returns a result object consumable by the hook system

## Dependencies

Parent: [Epic 001](001-epic-filter-engine.md) — Core Filter Engine
Depends on: [001-01](001-01-classifier.md), [001-02](001-02-registry.md)

## Estimated Effort

~100 lines, 1 hour
