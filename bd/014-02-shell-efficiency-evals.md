---
id: "014-02"
title: "Shell Efficiency Evals — Verify --silent, --no-pager, --quiet Flag Usage"
status: closed
epic: "014"
labels: ["evals", "shell", "efficiency", "flags", "behavioral", "P2"]
created: "2025-07-14"
priority: "P2"
---

## Summary

Behavioral tests that verify the agent uses efficiency flags when running shell commands. Tests: npm install → should include --silent or --quiet; git log → should include --no-pager; cargo build → should include --quiet. Match against tool call arguments using regex or string contains. Handle edge cases: agent already used flags, non-applicable commands.

## Motivation

Shell efficiency is a core Muse behavior. These evals catch regressions where the agent forgets to add --silent, --no-pager, or --quiet, keeping output clean and token usage low.

## Deliverables

- 3 evalTest definitions (npm_silent, git_no_pager, cargo_quiet)
- Assert functions that check `toolCall.args.command` for expected flags

## Acceptance Criteria

- [x] Each test passes when agent uses correct flags
- [x] Each fails with descriptive message when flags missing
- [x] Handles different flag variants (-q vs --quiet)

## Dependencies

Parent: [Epic 014](014-epic-behavioral-evals.md) — Behavioral Eval Framework. Depends on [014-01](014-01-eval-runner.md).

## Estimated Effort

~80 lines, 40 min
