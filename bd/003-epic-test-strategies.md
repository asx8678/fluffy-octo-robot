---
id: "003"
title: "Epic: Test Runner Failure Focus — Pytest/Vitest/Jest/Cargo/Rspec"
status: closed
epic: "003"
labels: ["epic", "tests", "pytest", "jest", "vitest", "cargo", "rspec", "P1"]
created: "2025-07-14"
priority: "P1"
---

## Summary

State machine parsers for major test runners: pytest, vitest, jest, cargo test, rspec, go test. Implement failure-only mode that hides passing tests and surfaces only errors + summary.

## Motivation

Test output often dwarfs actual code changes. In CI and agent workflows, passing tests are noise. RTK's failure-focus approach cut test tokens by 90% while preserving every actionable detail.

## Deliverables

1. Pytest text state machine — track test lifecycle, failures only + summary
2. Vitest/Jest JSON parser — failures only extraction
3. Cargo test / RSpec — NDJSON/JSON parsing

## Acceptance Criteria

- [x] Pytest parser tracks setup/call/teardown lifecycle, reports failures + error tracebacks
- [x] Vitest/Jest parsers ingest JSON output, hide passing suites
- [x] Cargo test parser handles NDJSON streaming, extracts failure details
- [x] RSpec parser handles JSON formatter output
- [x] Each parser supports `-v` to show passing tests if needed

## Dependencies

Depends on [Epic 001](001-epic-filter-engine.md) — Core Filter Engine

## Estimated Effort

~300 lines, 3 hours

## Children

- [003-01](003-01-pytest.md) — Pytest parser
- [003-02](003-02-vitest-jest.md) — Vitest/Jest parser
- [003-03](003-03-cargo-rspec.md) — Cargo test / RSpec parser
