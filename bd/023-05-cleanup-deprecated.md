---
id: "023-05"
title: "Phase 5: Cleanup — Deprecated APIs, Ruff & Mypy Rules"
status: open
epic: "023"
labels: ["modernization", "py314", "cleanup", "P1"]
created: "2025-07-16"
priority: "P1"
---

## Summary

Update project configuration to target Python 3.14, enable strict linting and type-checking, and run automated fixes across the entire codebase. Verify no deprecated 3.14 APIs are in use.

## Motivation

Moving the floor to 3.14 means we can turn on stricter tooling. Running `ruff` and `mypy` with py314 targets catches latent issues and enforces consistency going forward.

## Deliverables

- Update `pyproject.toml`: `requires-python = ">=3.14,<3.16"`, update classifiers
- Add `[tool.ruff]` target-version = "py314", add rule set `py314`
- Add `[tool.mypy]` python_version = "3.14", strict = true
- Run `ruff check --fix` and `ruff format .` across entire codebase
- Run `mypy --python-version 3.14 --strict code_muse/` (incrementally, fix issues)
- Verify no `argparse.BooleanOptionalAction`, `ast.Bytes` usage (not present — skip)

## Acceptance Criteria

- [ ] `uv build` succeeds after pyproject.toml changes
- [ ] `ruff check` clean across entire codebase
- [ ] `ruff format .` clean (no changes on second run)
- [ ] `mypy --python-version 3.14 --strict` clean, or exceptions documented with inline comments
- [ ] No deprecated 3.14 APIs in use
- [ ] Classifiers in pyproject.toml match new version range

## Dependencies

Parent: [Epic 023](023-epic-py314-modernization.md)

## Estimated Effort

~300 lines, 2–3 hours
