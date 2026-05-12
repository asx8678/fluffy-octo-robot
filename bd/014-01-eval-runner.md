---
id: "014-01"
title: "Eval Runner + Test Rig — Load Evals, Execute, Report Pass/Fail"
status: closed
epic: "014"
labels: ["evals", "runner", "test", "rig", "behavioral", "P2"]
created: "2025-07-14"
priority: "P2"
---

## Summary

Build the eval runner infrastructure. evalTest(name, prompt, files, assert_fn) helper that sets up a test scenario (optionally creates files), runs the agent with the given prompt, captures tool call logs, and passes a test rig to the assert function. Runner loads all eval files from evals/ directory, executes each, reports pass/fail with descriptive output. Integrate with pytest or run standalone.

## Motivation

Behavioral evals verify agent quality in ways unit tests cannot. A reusable runner and rig lowers the cost of adding new behavioral tests and makes regressions easy to spot in CI.

## Deliverables

- `evalTest` function
- `TestRig` class with `readToolLogs() → list[ToolCall]`
- `run_all_evals() → results` dict
- Eval suite loader

## Acceptance Criteria

- [x] evalTest creates files if specified
- [x] Agent receives prompt
- [x] Tool logs captured
- [x] Assert receives rig with tool calls
- [x] Pass/fail reported clearly
- [x] CI can run evals

## Dependencies

Parent: [Epic 014](014-epic-behavioral-evals.md) — Behavioral Eval Framework

## Estimated Effort

~100 lines, 45 min
