---
id: "014-05"
title: "Memory + Planning Evals — Verify save_memory Fidelity + Plan Mode Flow"
status: closed
epic: "014"
labels: ["evals", "memory", "planning", "behavioral", "P2"]
created: "2025-07-14"
priority: "P2"
---

## Summary

Behavioral tests for save_memory and plan mode. save_memory test: agent encounters a fact, calls save_memory, assert fact correctly captured (no hallucination). Plan mode test: agent enters plan mode via /plan, generates plan.md, awaits approval before implementing.

## Motivation

Memory fidelity and plan-mode discipline are high-level agent behaviors that unit tests cannot cover. These evals ensure the agent remembers accurately and respects the plan/approve workflow.

## Deliverables

- 2 evalTest definitions (save_memory_fidelity, plan_mode_flow)
- Assert functions check tool call sequences and output content

## Acceptance Criteria

- [x] save_memory captures correct fact text
- [x] Plan mode denies write_file before approval
- [x] plan.md exists with expected structure
- [x] Approval flow works

## Dependencies

Parent: [Epic 014](014-epic-behavioral-evals.md) — Behavioral Eval Framework. Depends on [014-01](014-01-eval-runner.md).

## Estimated Effort

~40 lines, 20 min
