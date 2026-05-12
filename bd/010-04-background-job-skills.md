---
id: "010-04"
title: "Background Job Skills"
status: closed
epic: "010"
labels: ["skills", "background", "job", "async", "headless", "P1"]
created: "2025-07-14"
priority: "P1"
---

## Summary

Support skills that spawn background agent processes. Pattern: skill includes scripts/run.sh that invokes gemini/code-muse headlessly with -p flag. Agent creates ephemeral git worktree in .muse/tmp/. Skill check script returns STATUS: IN_PROGRESS or STATUS: COMPLETE with log paths. Main agent reads logs and synthesizes final assessment.

## Motivation

Some tasks (long-running analysis, large refactors, batch migrations) should not block the main agent session. Background job skills let the agent delegate and resume later.

## Deliverables

- Background job skill pattern: `scripts/run.sh` invoking headless agent
- Ephemeral git worktree creation in `.muse/tmp/`
- Status check protocol: `STATUS: IN_PROGRESS` or `STATUS: COMPLETE`
- Log path reporting and log reading by the main agent
- Final assessment synthesis from background job output

## Acceptance Criteria

- [x] Skill can declare itself as a background job via `scripts/run.sh`
- [x] Headless invocation uses `-p` flag for non-interactive mode
- [x] Ephemeral git worktree created and cleaned up appropriately
- [x] Status check script returns `STATUS: IN_PROGRESS` or `STATUS: COMPLETE`
- [x] On complete, log paths are reported and readable by the main agent
- [x] Main agent synthesizes a final assessment from background job logs
- [x] Failed or timed-out background jobs handled gracefully

## Dependencies

Parent: [Epic 010](010-epic-skills-system.md) — Skills System

## Estimated Effort

~100 lines, 45 min
