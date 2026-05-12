---
id: "024-07"
title: "Document run_shell_command Hook Execution Priority (P3)"
status: open
epic: "024"
labels: ["docs", "hooks", "P3"]
created: "2026-05-18"
priority: "P3"
---

## Summary

Three plugins register for the `run_shell_command` hook: `filter_engine`, `shell_minimizer`, and `policy_engine`. The execution order depends on plugin import order (alphabetical directory scan in `plugins/__init__.py`), but this priority is not documented. A developer adding a fourth handler would not know which result "wins."

## Recommended Action

1. Add a docstring to the `run_shell_command` hook definition in `callbacks.py` explaining execution order and that the first non-`None` result with `pre_executed: True` wins.
2. Add a comment in each plugin's `run_shell_command` callback noting its intended priority relative to others.

## Deliverables

- [ ] Docstring added to `run_shell_command` in `code_muse/callbacks.py`
- [ ] Priority comments added to `filter_engine/register_callbacks.py`, `shell_minimizer/register_callbacks.py`, `policy_engine/register_callbacks.py`
- [ ] No code changes required (documentation only)

## Acceptance Criteria

- [ ] Docstring is accurate and complete
- [ ] Anyone reading the code can understand which plugin's result will be applied

## Dependencies

Parent: [Epic 024](024-epic-code-health.md)

## Estimated Effort

~20 lines added, 10 minutes
