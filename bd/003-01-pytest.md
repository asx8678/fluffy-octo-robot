---
id: "003-01"
title: "Pytest Text State Machine — Failures Only + Summary"
status: closed
epic: "003"
labels: ["tests", "pytest", "state-machine", "parser", "failure-focus", "P1"]
created: "2025-07-14"
priority: "P1"
---

## Summary

Build a text state machine parser for pytest output that tracks test lifecycle (setup/call/teardown), hides passing tests, and surfaces only failures + summary statistics.

## Motivation

Pytest output is verbose: every passing test prints a dot or line. A medium test suite can emit 500+ lines. Failure-focus mode collapses this to the failures (usually <10%) plus a summary.

## Deliverables

- State machine tracking: `PASSED`, `FAILED`, `ERROR`, `SKIPPED`
- Extract failure tracebacks and error messages
- Summary line: passed, failed, error, skipped, duration
- Support for `pytest -v` and `pytest -vv` escalation

## Acceptance Criteria

- [x] Passing tests produce no output in default mode
- [x] Each failed test shows name, traceback, and assertion error
- [x] Summary shows total counts and duration
- [x] `ERROR` in setup/teardown is surfaced distinctly from `FAILED`
- [x] Handles parametrized tests (`test_foo[bar-1]`)
- [x] Works with `pytest-xdist` output (interleaved lines)

## Dependencies

Parent: [Epic 003](003-epic-test-strategies.md) — Test Runner Failure Focus

## Estimated Effort

~120 lines, 1 hour
