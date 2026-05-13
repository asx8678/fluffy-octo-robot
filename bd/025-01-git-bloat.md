---
id: "025-01"
title: "Remove generated data files from git tracking (P1)"
status: open
epic: "025"
labels: ["cleanup", "git", "P1"]
created: "2026-05-18"
priority: "P1"
---

## Summary

Remove `coverage.json` (1.6 MB) and `pre_refactor_hashes.txt` (917 KB) from git tracking and add both to `.gitignore`.

## Motivation

These generated artifacts bloat every clone by ~2.5MB. They are not source code and have no business being version-controlled. `coverage.json` is a pytest-cov report artifact. `pre_refactor_hashes.txt` is an audit trail from a refactoring tool.

## Deliverables

- [ ] `git rm --cached coverage.json pre_refactor_hashes.txt`
- [ ] Add both patterns to `.gitignore`
- [ ] Verify with `git status` that they are no longer tracked
- [ ] Confirm no code or workflow depends on these files
- [ ] All existing tests pass

## Dependencies

Parent: [Epic 025](025-epic-code-review-remediation.md)

## Estimated Effort

~10 lines changed, 10 minutes
