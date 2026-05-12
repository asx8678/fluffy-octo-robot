---
id: "001-05"
title: "Add -u/--ultra-compact and -v/-vv/-vvv Flags"
status: closed
epic: "001"
labels: ["filter-engine", "cli", "flags", "verbosity", "P0"]
created: "2025-07-14"
priority: "P0"
---

## Summary

Add CLI flags to control filtering verbosity: `-u`/`--ultra-compact` for maximum compression, and `-v`/`-vv`/`-vvv` for progressively more raw output.

## Motivation

Different contexts need different compression levels. A one-line summary is great for quick checks; full output is needed for deep debugging. Flags give users (and the LLM) control.

## Deliverables

- `-u` / `--ultra-compact` flag (max compression)
- `-v` flag (moderate detail)
- `-vv` flag (more detail)
- `-vvv` flag (raw / passthrough)
- Flag propagation through dispatcher to strategies

## Acceptance Criteria

- [x] Flags are parsed and stored in a config/ctx object
- [x] Strategies receive the verbosity level and adjust output
- [x] `-u` overrides all strategies to their most compact mode
- [x] `-vvv` bypasses filtering entirely (passthrough)
- [x] Default level (no flags) applies standard compression

## Dependencies

Parent: [Epic 001](001-epic-filter-engine.md) — Core Filter Engine
Depends on: [001-03](001-03-dispatcher.md)

## Estimated Effort

~50 lines, 30 minutes
