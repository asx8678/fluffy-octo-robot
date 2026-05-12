---
id: "011-02"
title: "Policy Evaluator — Match Tool Calls Against Rules, Highest Priority Wins"
status: closed
epic: "011"
labels: ["policy", "evaluator", "match", "decision", "P1"]
created: "2025-07-14"
priority: "P1"
---

## Summary

Given a tool call (toolName, command for shell calls) and a list of ToolRules, find the matching rule with highest priority. Match: toolName exact or wildcard match, then commandPrefix startswith check (only for run_shell_command). Return the decision (allow/deny/ask_user). Default when no rules match: allow. Log evaluation for audit trail.

## Motivation

The evaluator is the runtime brain of the policy engine. It must be deterministic, fast, and transparent — every tool call gets a clear decision that can be traced back to a specific rule.

## Deliverables

- `evaluate_policy(tool_name, command, rules)` → (decision, matched_rule | None)
- Priority tie-breaking: first registered wins (or error if equal priority with different decisions)

## Acceptance Criteria

- [x] exact toolName match wins over wildcard
- [x] commandPrefix filters after toolName match
- [x] highest priority rule selected
- [x] no rules = allow
- [x] log shows which rule matched

## Dependencies

Parent: [Epic 011](011-epic-policy-engine.md) — Policy Engine
Depends on: [011-01](011-01-policy-toml-schema.md) — Policy TOML Schema + Parser

## Estimated Effort

~60 lines, 30 min
