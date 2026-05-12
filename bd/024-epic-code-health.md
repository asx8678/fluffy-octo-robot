---
id: "024"
title: "Epic: Code Health & Integration Audit — Post-Review Remediation"
status: open
epic: "024"
labels: ["epic", "code-health", "P0", "security", "audit"]
created: "2026-05-18"
priority: "P0"
---

## Summary

Comprehensive remediation of issues discovered during the senior architect code review (2026-05-18). Covers critical Python 3 syntax errors that would crash on startup, missing dependency resolution, dead code removal, import hygiene, refactoring of god-functions, type-location hygiene, and hook execution priority documentation.

## Motivation

The review uncovered 8 critical syntax errors (Python 2-style `except` clauses), a missing `annotationlib` dependency that breaks imports, dead code in checkpointing and command_handler, redundant in-function imports in `cli_runner.py`, an unmaintainably large `interactive_mode` function (~560 lines), a core plugin type (`MarkdownCommandResult`) imported from a specific plugin rather than a shared location, and undocumented hook execution priority for `run_shell_command` callbacks.

Left unfixed, the syntax errors would prevent application startup on Python 3.14+. The other issues degrade maintainability and create hidden coupling.

## Source

Findings from comprehensive code review by `planning-agent-f77d40` (2026-05-18).

## Deliverables

1. Fix all 8 Python 2-style `except X, Y:` → `except (X, Y):` syntax errors
2. Resolve `annotationlib` dependency (add to pyproject.toml or inline)
3. Remove dead code (disabled rewind listener, legacy fallback section)
4. Clean redundant in-function imports from `cli_runner.py`
5. Extract `interactive_mode` sub-functions to reduce cyclomatic complexity
6. Move `MarkdownCommandResult` to a shared types location
7. Document `run_shell_command` hook execution priority ordering

## Acceptance Criteria

- [ ] All 8 `except` syntax errors fixed; `ruff check` passes on all affected files
- [ ] `annotationlib` importable at startup (either as dependency or inlined)
- [ ] Dead code removed without regressions
- [ ] `cli_runner.py` has ≤3 in-function imports (only where module-level import would cause circular deps)
- [ ] `interactive_mode` split into ≤5 helper functions, each ≤100 lines
- [ ] `MarkdownCommandResult` lives in `code_muse/command_line/types.py` (or similar) and is imported from there by both `command_handler.py` and `customizable_commands/register_callbacks.py`
- [ ] `run_shell_command` callback docstring or hook docs explain priority order
- [ ] All existing tests pass

## Dependencies

None — this epic is self-contained and blocks no other work.

## Estimated Effort

~600 lines changed, 5–8 hours

## Children

- [024-01](024-01-critical-syntax-fixes.md) — Critical Python 2-Style `except` Syntax Fixes (P0)
- [024-02](024-02-dependency-annotationlib.md) — Missing `annotationlib` Dependency Resolution (P0)
- [024-03](024-03-dead-code-cruft.md) — Dead Code & Cruft Elimination (P1)
- [024-04](024-04-import-cleanup.md) — Redundant Import Cleanup in `cli_runner.py` (P2)
- [024-05](024-05-large-function-refactor.md) — Refactor `interactive_mode` God-Function (P2)
- [024-06](024-06-shared-type-extraction.md) — Extract `MarkdownCommandResult` to Shared Location (P2)
- [024-07](024-07-hook-priority-docs.md) — Document `run_shell_command` Hook Execution Priority (P3)
