---
id: "025-05"
title: "Consolidate bloated test file triplicates (P2)"
status: open
epic: "025"
labels: ["tests", "maintainability", "P2"]
created: "2026-05-18"
priority: "P2"
---

## Summary

Audit and consolidate the many `test_*_coverage.py`, `test_*_extended.py`, `test_*_full_coverage.py`, and `test_*_missing.py` files. Merge genuine unique tests into the primary test file and remove redundant coverage scaffolding.

## Motivation

The test suite has grown organically by coverage chasing, creating triplicates like:
- `test_command_runner_core.py` + `test_command_runner_coverage.py` + `test_command_runner_extended.py` + `test_command_runner_full_coverage.py` + `test_command_runner_comprehensive.py`
- Similar patterns across tools, plugins, agents, command_line tests

This makes the test suite harder to navigate, slows CI, and suggests many "coverage" tests exist only to satisfy a coverage threshold rather than testing real behavior.

## Audit approach

For each triplicate:
1. Identify unique test cases (not redundant with primary file)
2. Move unique tests into the primary test file
3. Delete the scaffolding files
4. Update coverage config if needed
5. Run full test suite to confirm no regression

## Deliverables

- [ ] Audit all `test_*_coverage.py` files — merge unique tests or delete
- [ ] Audit all `test_*_extended.py` files — merge unique tests or delete
- [ ] Audit all `test_*_full_coverage.py` files — merge unique tests or delete
- [ ] Audit all `test_*_missing.py` files — merge unique tests or delete
- [ ] Run full test suite and confirm no regressions
- [ ] Update TESTING.md if test file references changed

## Dependencies

Parent: [Epic 025](025-epic-code-review-remediation.md)

## Estimated Effort

~300 lines changed (deletions), 4–6 hours of audit work
