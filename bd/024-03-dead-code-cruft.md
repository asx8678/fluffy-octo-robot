---
id: "024-03"
title: "Dead Code & Cruft Elimination (P1)"
status: open
epic: "024"
labels: ["cleanup", "dead-code", "P1"]
created: "2026-05-18"
priority: "P1"
---

## Summary

Remove identified dead code and useless placeholder sections that increase maintenance burden without providing value.

## Items to Remove

### 1. Disabled Rewind Listener in Checkpointing Plugin

**File:** `code_muse/plugins/checkpointing/register_callbacks.py:47-52`

The `_on_startup` function body is just `pass` with a comment explaining why the feature was disabled.
**Action:** Remove `_on_startup` function and its `register_callback("startup", _on_startup)` call.

### 2. Legacy Command Fallback Section in Command Handler

**File:** `code_muse/command_line/command_handler.py:224-238`

Entirely commented-out example code block with no real legacy commands.
**Action:** Remove the entire `# LEGACY COMMAND FALLBACK` section.

## Deliverables

- [ ] Remove disabled rewind listener function and its registration
- [ ] Remove legacy command fallback comment block from `command_handler.py`
- [ ] Verify no functionality is lost

## Acceptance Criteria

- [ ] `ruff check` passes on changed files
- [ ] All existing tests pass
- [ ] `/restore` slash command still works (checkpointing plugin unaffected)

## Dependencies

Parent: [Epic 024](024-epic-code-health.md)

## Estimated Effort

~40 lines removed, 15 minutes
