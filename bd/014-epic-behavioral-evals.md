---
id: "014"
title: "Epic: Behavioral Eval Framework — Shell Efficiency, Frugal Reads, Tool Masking Tests"
status: closed
epic: "014"
labels: ["epic", "evals", "behavioral", "testing", "quality", "P2"]
created: "2025-07-14"
priority: "P2"
---

## Summary

Port Gemini CLI's behavioral eval framework. Tests that verify agent exhibits specific behaviors: shell efficiency (`--silent`, `--no-pager`), frugal reads (ranged reads, batch nearby), tool output masking, save_memory fidelity, etc.

## Motivation

Muse has extensive unit tests but no behavioral eval framework. These tests catch agent quality regressions that unit tests miss.

## Deliverables

1. Eval test runner + assert helpers
2. Shell efficiency evals (npm install --silent, git --no-pager)
3. Frugal reads evals (ranged reads, batch nearby ranges)
4. Tool output masking eval
5. Save memory fidelity eval

## Acceptance Criteria

- [x] Eval runner loads evals from `evals/` directory
- [x] Each eval has name, prompt, and assert function
- [x] Assert receives test rig with tool logs
- [x] Behavioral tests run as part of CI
- [x] Failures produce descriptive messages showing expected vs actual behavior

## Dependencies

Depends on Epics 001–005 (filter strategies must exist to test shell efficiency).

## Estimated Effort

~350 lines, 3 hours

## Children

- [014-01](014-01-eval-runner.md) — Eval Runner + Test Rig (evalTest helper, readToolLogs, assert helpers)
- [014-02](014-02-shell-efficiency.md) — Shell Efficiency Evals (npm/pnpm --silent, git --no-pager, cargo --quiet)
- [014-03](014-03-frugal-reads.md) — Frugal Reads Evals (ranged reads, batch nearby, avoid full-file reads)
- [014-04](014-04-tool-masking.md) — Tool Output Masking Evals (secrets redaction, token masking)
- [014-05](014-05-memory-planning.md) — Memory + Planning Evals (save_memory fidelity, plan mode behavior)
