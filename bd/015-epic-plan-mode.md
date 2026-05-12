---
id: "015"
title: "Epic: Plan Mode — Read-Only Research, Markdown Plans, External Editor"
status: closed
epic: "015"
labels: ["epic", "plan", "readonly", "research", "editor", "P2"]
created: "2025-07-14"
priority: "P2"
---

## Summary

Port Gemini CLI's Plan Mode. Read-only environment where agent researches → discusses strategy → creates detailed markdown plan → user approves → agent implements. Shift+Tab cycles modes. Plan files stored in `plans/` directory, editable via external editor (Ctrl+X).

## Motivation

Muse has agent_planning.py but no formal plan-mode with markdown file generation, external editor, or mode cycling.

## Deliverables

1. `enter_plan_mode` tool (read-only, no file mutations allowed)
2. Plan generation (research → discuss → draft plan.md)
3. Plan approval flow (review, edit, approve, cancel)
4. Mode cycling (Shift+Tab: default → auto-edit → plan)
5. `/plan` slash command

## Acceptance Criteria

- [x] Plan mode denies write_file, replace_in_file, and run_shell_command
- [x] Agent can read files and search while in plan mode
- [x] plan.md generated in `plans/` directory with structured sections
- [x] Ctrl+X opens external editor on current plan file
- [x] Approve transitions to auto-edit or manual-edit mode
- [x] `/plan [goal]` shortcut enters plan mode with provided goal

## Dependencies

Depends on Epic 008 (Checkpointing) for safe mode transitions.

## Estimated Effort

~300 lines, 2.5 hours

## Children

- [015-01](015-01-enter-plan-mode.md) — enter_plan_mode Tool (read-only enforcement, tool allowlist)
- [015-02](015-02-plan-generation.md) — Plan Generation + Storage (research→discuss→draft, plans/ directory)
- [015-03](015-03-plan-approval.md) — Plan Approval Flow (review prompt, edit via Ctrl+X, approve/cancel)
- [015-04](015-04-mode-cycling.md) — Mode Cycling + /plan Command (Shift+Tab cycling, /plan [goal] shortcut)
