---
id: "011-04"
title: "Approval Flow Integration — Map Policy Decisions to Tool Approval Pipeline"
status: closed
epic: "011"
labels: ["policy", "approval", "integration", "hook", "P1"]
created: "2025-07-14"
priority: "P1"
---

## Summary

Hook the policy evaluator into the existing tool approval flow (pre-tool-use callback). Before showing user confirmation for a tool call, check policy rules. Map decisions: allow → skip user confirmation entirely (auto-approve), deny → block with reason message (policy: <rule>), ask_user → proceed with normal confirmation flow. Policy check runs before other approval hooks. Log all decisions.

## Motivation

Policy rules are only useful if they actually gate tool execution. Integrating before the existing approval hook preserves all current safety behavior while adding a new, user-configurable layer on top.

## Deliverables

- `integrate_policy_check(tool_call_context)` → approval_action
- policy_bypass_logger

## Acceptance Criteria

- [x] allow skips confirmation
- [x] deny blocks with message
- [x] ask_user shows normal prompt
- [x] policy runs before destructive command guard
- [x] log records decision and matching rule

## Dependencies

Parent: [Epic 011](011-epic-policy-engine.md) — Policy Engine
Depends on: [011-02](011-02-policy-evaluator.md) — Policy Evaluator, [011-03](011-03-policy-file-discovery.md) — Policy File Discovery

## Estimated Effort

~50 lines, 25 min
