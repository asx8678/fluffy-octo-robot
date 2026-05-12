---
id: "015-01"
title: "Enter Plan Mode Tool — Read-Only Agent State with Tool Allowlist"
status: closed
epic: "015"
labels: ["plan", "mode", "readonly", "tool", "P2"]
created: "2025-07-14"
priority: "P2"
---

## Summary

Implement the enter_plan_mode tool that switches the agent to a read-only planning state. While in plan mode, only read tools are allowed (read_file with ranged reads, search, glob, grep, list_files). Write tools (write_file, replace_in_file) and shell execution (run_shell_command) are blocked. Agent can still use ask_user for clarifications. Set a plan_mode flag in agent runtime state.

## Motivation

Gemini CLI's plan mode prevents accidental file mutations during research and design phases. This is the foundation for structured planning.

## Deliverables

- enter_plan_mode() function/tool
- Tool allowlist for plan mode
- Mode flag in agent state
- Mode change notification to UI

## Acceptance Criteria

- [x] write_file blocked in plan mode with clear message
- [x] run_shell_command blocked
- [x] read_file/search/glob/grep allowed
- [x] mode flag visible in UI
- [x] exit_plan_mode restores full tools

## Dependencies

Parent: [Epic 015](015-epic-plan-mode.md)

## Estimated Effort

~80 lines, 40 min
