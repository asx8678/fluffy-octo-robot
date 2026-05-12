---
id: "024-04"
title: "Redundant Import Cleanup in cli_runner.py (P2)"
status: open
epic: "024"
labels: ["cleanup", "imports", "P2"]
created: "2026-05-18"
priority: "P2"
---

## Summary

`code_muse/cli_runner.py` imports `emit_info`, `emit_error`, `emit_warning`, `emit_success`, `emit_system_message` at module level (lines 38, 187) but then re-imports them inside individual functions at lines 242, 398, 447, 492, 503, 512, 858, 1065, 1091, 1095. This is redundant.

## Affected Functions

`main()`, `interactive_mode()`, `run_prompt_with_attachments()`, `execute_single_prompt()` — all re-import messaging functions already available at module scope.

## Deliverables

- [ ] Remove all redundant in-function imports of messaging functions
- [ ] Keep only in-function imports that are truly necessary (e.g., `get_message_bus` used once)
- [ ] Verify no circular import issues arise

## Acceptance Criteria

- [ ] `ruff check` passes on `cli_runner.py`
- [ ] Application starts and runs interactive mode correctly

## Dependencies

Parent: [Epic 024](024-epic-code-health.md)

## Estimated Effort

~15 lines removed, 10 minutes
