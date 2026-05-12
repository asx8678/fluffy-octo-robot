---
id: "014-04"
title: "Tool Output Masking Evals — Verify Secret Redaction in Shell/Read Output"
status: closed
epic: "014"
labels: ["evals", "masking", "secrets", "output", "security", "P2"]
created: "2025-07-14"
priority: "P2"
---

## Summary

Behavioral tests that verify the agent masks secrets (API keys, tokens, passwords) in tool output before showing to user. Test with a file containing fake secrets. Prompt agent to read it or grep for a pattern. Assert that output shown to user has secrets replaced with [REDACTED] or similar.

## Motivation

Secret leakage through tool output is a security risk. These evals verify that redaction is applied consistently across read_file, grep, and shell output before it reaches the user.

## Deliverables

- 1 evalTest (secret_masking)
- Setup creates file with fake `API_KEY=sk-abc123`
- Assert checks displayed output for redaction markers and absence of raw secret

## Acceptance Criteria

- [x] Secrets not visible in displayed output
- [x] Redaction marker present
- [x] Works for read_file, grep, and shell cat commands

## Dependencies

Parent: [Epic 014](014-epic-behavioral-evals.md) — Behavioral Eval Framework. Depends on [014-01](014-01-eval-runner.md).

## Estimated Effort

~60 lines, 30 min
