---
id: "003-03"
title: "Cargo Test / RSpec — NDJSON/JSON Parsing"
status: closed
epic: "003"
labels: ["tests", "cargo", "rspec", "ndjson", "json", "parser", "P1"]
created: "2025-07-14"
priority: "P1"
---

## Summary

Parse Cargo test's NDJSON output and RSpec's JSON formatter output to extract failures and summaries.

## Motivation

Cargo emits one JSON object per test when run with `--message-format=json` or via `cargo test -- --nocapture` with custom harnesses. RSpec supports `--format json`. Both are ideal for programmatic parsing.

## Deliverables

- Cargo NDJSON parser: `type=test`, `event=failed`
- RSpec JSON parser: `examples[].status`, `exceptions[]`
- Failure extraction and summary
- Graceful fallback for unsupported harnesses

## Acceptance Criteria

- [x] Cargo parser handles `test` and `suite` events
- [x] RSpec parser handles `passed`, `failed`, `pending` statuses
- [x] Failure output includes test name, file/line, and message
- [x] Summary shows total, passed, failed, ignored
- [x] Falls back to passthrough if JSON/NDJSON not detected

## Dependencies

Parent: [Epic 003](003-epic-test-strategies.md) — Test Runner Failure Focus

## Estimated Effort

~100 lines, 1 hour
