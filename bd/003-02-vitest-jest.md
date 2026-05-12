---
id: "003-02"
title: "Vitest/Jest JSON Parser — Failures Only Extraction"
status: closed
epic: "003"
labels: ["tests", "vitest", "jest", "json", "parser", "failure-focus", "P1"]
created: "2025-07-14"
priority: "P1"
---

## Summary

Parse Vitest and Jest JSON output (`--json` or `reporter=json`) to extract only failing tests, hiding passing suites and tests.

## Motivation

Vitest and Jest both support JSON reporters, which is cleaner than text scraping. Parsing JSON lets us precisely extract failure messages, stack traces, and suite context.

## Deliverables

- Jest JSON parser: `testResults[].message`, `status`
- Vitest JSON parser: `testResults`, `errors`
- Failure-only formatter
- Summary statistics

## Acceptance Criteria

- [x] Passing tests/suites are suppressed
- [x] Each failure shows test name, file path, and error message
- [x] Summary shows total passed, failed, skipped, duration
- [x] Handles JSON parse errors gracefully (fall back to text passthrough)
- [x] Works with both inline and external JSON reporter output

## Dependencies

Parent: [Epic 003](003-epic-test-strategies.md) — Test Runner Failure Focus

## Estimated Effort

~80 lines, 45 minutes
