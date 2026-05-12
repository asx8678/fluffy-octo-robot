---
id: "011"
title: "Epic: Policy Engine — TOML Rules for Tool Allow/Deny/Ask"
status: closed
epic: "011"
labels: ["epic", "policy", "rules", "toml", "security", "P1"]
created: "2025-07-14"
priority: "P1"
---

## Summary

Port Gemini CLI's TOML-based policy engine. Rules define toolName + commandPrefix + decision (allow/deny/ask_user) + priority. Wildcards supported. Loaded from `~/.muse/policies/*.toml` and project `.muse/policies/*.toml`.

## Motivation

Muse has destructive_command_guard and shell_safety plugins. Gemini's engine is more general (any tool, not just shell) and uses TOML format compatible with filter pipeline.

## Deliverables

1. TOML rule parser + validator
2. Policy evaluator (match tool call against rules, highest priority wins)
3. Policy file discovery (user + project tiers)
4. Integration with tool approval flow

## Acceptance Criteria

- [x] Rules match by toolName with wildcard `*` supported
- [x] commandPrefix matches start of shell command strings
- [x] Decision `deny` blocks execution without user prompt
- [x] Decision `ask_user` triggers interactive confirmation
- [x] Decision `allow` bypasses confirmation
- [x] Priority resolves conflicts (highest wins)
- [x] Unknown tools pass through without policy interference

## Dependencies

None. Standalone.

## Estimated Effort

~250 lines, 2 hours

## Children

- [011-01](011-01-policy-toml-schema.md) — Policy TOML Schema + Parser (ToolRule, decision enum, priority, validation)
- [011-02](011-02-policy-evaluator.md) — Policy Evaluator (match toolName + commandPrefix, highest-priority-wins)
- [011-03](011-03-policy-file-discovery.md) — Policy File Discovery (user ~/.muse/policies/ + project .muse/policies/)
- [011-04](011-04-approval-flow-integration.md) — Approval Flow Integration (hook into pre-tool-use, apply decision)
