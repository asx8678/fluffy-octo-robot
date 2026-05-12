---
id: "014-03"
title: "Frugal Reads Evals — Verify Ranged Reads + Batch Nearby Ranges"
status: closed
epic: "014"
labels: ["evals", "frugal", "reads", "ranged", "behavioral", "P2"]
created: "2025-07-14"
priority: "P2"
---

## Summary

Behavioral tests that verify the agent reads files frugally. Create a test file with errors at lines 500, 510, 520. Prompt: "fix linter errors in linter_mess.ts". Assert that agent uses ranged reads (start_line/num_lines) instead of reading entire file, and that nearby ranges (500-520) are batched into 1-3 contiguous reads, all in the same turn.

## Motivation

Full-file reads waste tokens and slow down large-file tasks. These evals enforce the ranged-read discipline and batching heuristic that keeps the agent efficient.

## Deliverables

- 1 evalTest (frugal_reads_scenario)
- Setup creates large file with scattered errors
- Assert checks read_file tool call arguments for start_line/num_lines and count

## Acceptance Criteria

- [x] Agent uses ≤3 read_file calls for 3 nearby errors
- [x] All reads in same turn
- [x] No full-file reads
- [x] Works with different line counts

## Dependencies

Parent: [Epic 014](014-epic-behavioral-evals.md) — Behavioral Eval Framework. Depends on [014-01](014-01-eval-runner.md).

## Estimated Effort

~70 lines, 35 min
