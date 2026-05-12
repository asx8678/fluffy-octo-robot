---
id: "013-03"
title: "{{args}} Injection — Replace Placeholder with User Arguments, Shell-Aware Mode"
status: closed
epic: "013"
labels: ["commands", "args", "injection", "placeholder", "P2"]
created: "2025-07-14"
priority: "P2"
---

## Summary

When a custom command is invoked with arguments (e.g., `/git:fix Button misaligned`), replace {{args}} in the prompt with the argument text. Two modes: raw (direct string substitution in the prompt body) and shell-context-aware (when prompt includes a run_shell_command block, automatically append efficiency flags like --silent/--quiet/--no-pager to the shell command). Detect shell blocks by scanning for ```bash or run_shell_command tool references.

## Motivation

`{{args}}` makes custom commands flexible. Shell-aware injection goes further by auto-adding efficiency flags, reinforcing frugal shell usage without requiring users to edit prompts.

## Deliverables

- `inject_args(prompt: str, args: str) → str`
- `detect_shell_blocks(prompt: str) → bool`
- `auto_flag_shell_command(command: str) → str`

## Acceptance Criteria

- [x] {{args}} replaced with user text
- [x] No args = {{args}} removed (empty string)
- [x] Shell commands get efficiency flags appended
- [x] Multiple {{args}} all replaced

## Dependencies

Parent: [Epic 013](013-epic-custom-commands.md) — Custom Commands

## Estimated Effort

~60 lines, 30 min
