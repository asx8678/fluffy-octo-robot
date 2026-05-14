---
id: "024-05"
title: "Refactor interactive_mode God-Function (P2)"
status: closed
epic: "024"
labels: ["refactor", "complexity", "P2"]
created: "2026-05-18"
priority: "P2"
---

## Summary

The `interactive_mode` function in `code_muse/cli_runner.py` (~560 lines, lines 394–955) handles spinner management, tutorial onboarding, input gathering, clipboard, shell passthrough, autosave, command routing, agent response rendering, wiggum loop, and cancellation. Extremely high cyclomatic complexity.

## Proposed Extraction

Split into 5 helper functions:

1. **`_handle_initial_command(initial_command, agent, display_console)`** — Lines ~440–493
2. **`_show_startup_info(display_console)`** — Lines ~400–435
3. **`_run_main_input_loop(message_renderer, display_console)`** — Lines ~530–865
4. **`_wiggum_loop(current_agent, message_renderer, display_console)`** — Lines ~868–950
5. **`_render_and_autosave(result, current_agent, display_console)`** — Lines ~845–862, ~920–933

## Deliverables

- [ ] Extract the 5 helper functions
- [ ] `interactive_mode` reduced to ≤150 lines (orchestration only)
- [ ] No behavior changes
- [ ] All existing tests pass

## Acceptance Criteria

- [ ] `ruff check` passes on `cli_runner.py`
- [ ] Interactive mode works identically to current behavior
- [ ] All CLI tests pass

## Dependencies

Parent: [Epic 024](024-epic-code-health.md)

## Estimated Effort

~200 lines moved/reorganized, 2–3 hours

## Risk

Moderate — behavioral refactor of main user-facing loop. Must be tested in both interactive and `-p` modes.
