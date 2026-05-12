---
id: "024-06"
title: "Extract MarkdownCommandResult to Shared Location (P2)"
status: closed
epic: "024"
labels: ["refactor", "types", "coupling", "P2"]
created: "2026-05-18"
priority: "P2"
---

## Summary

`MarkdownCommandResult` is defined in `code_muse/plugins/customizable_commands/register_callbacks.py` but is imported by the core `command_handler.py` (line 251) via a fragile `try/except ImportError` pattern. Core infrastructure should not depend on a specific plugin's internal types.

## Proposed Solution

**Option A:** Create `code_muse/command_line/types.py` and define it there. Both `command_handler.py` and `customizable_commands/register_callbacks.py` import from there.

## Target Import Chain

```
code_muse/command_line/types.py  (new file)
  └─ class MarkdownCommandResult: ...

command_handler.py
  └─ from code_muse.command_line.types import MarkdownCommandResult

customizable_commands/register_callbacks.py
  └─ from code_muse.command_line.types import MarkdownCommandResult
```

## Deliverables

- [x] Create `MarkdownCommandResult` class in a shared location
- [x] Update `command_handler.py` to import directly (remove `try/except ImportError`)
- [x] Update `customizable_commands/register_callbacks.py` to import from shared location
- [x] Verify `/help` and other markdown commands work

## Acceptance Criteria

- [x] `ruff check` passes on changed files
- [x] `command_handler.py` no longer has `try/except ImportError` for `MarkdownCommandResult`
- [x] All existing tests pass

## Dependencies

Parent: [Epic 024](024-epic-code-health.md)

## Estimated Effort

~30 lines moved, 20 minutes
