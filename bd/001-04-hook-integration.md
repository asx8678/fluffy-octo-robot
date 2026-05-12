---
id: "001-04"
title: "Wire Filter Engine into pre_tool_call Hook"
status: closed
epic: "001"
labels: ["filter-engine", "hook", "integration", "plugin", "P0"]
created: "2025-07-14"
priority: "P0"
---

## Summary

Integrate the filter dispatcher into the `pre_tool_call` callback in the `claude_code_hooks` plugin so that shell tool invocations are automatically classified and filtered.

## Motivation

The hook system is Fast-Puppy's plugin interface. Wiring the filter engine there ensures every shell command flows through the classifier without requiring explicit user action.

## Deliverables

- Hook callback that intercepts `shell` tool calls
- Integration with classifier + dispatcher
- Return modified output to the caller

## Acceptance Criteria

- [x] `pre_tool_call` detects shell tool invocations
- [x] Extracts the command string from the tool call arguments
- [x] Routes through classifier → dispatcher → strategy
- [x] Returns filtered output as if it were the raw command output
- [x] Does not interfere with non-shell tools
- [x] Gracefully degrades if filter engine crashes

## Dependencies

Parent: [Epic 001](001-epic-filter-engine.md) — Core Filter Engine
Depends on: [001-03](001-03-dispatcher.md)

## Estimated Effort

~50 lines, 30 minutes
