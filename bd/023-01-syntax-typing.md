---
id: "023-01"
title: "Phase 1: Syntax & Typing Modernization"
status: closed
epic: "023"
labels: ["modernization", "py314", "syntax", "typing", "P0"]
created: "2025-07-16"
priority: "P0"
---

## Summary

Modernize all type annotations and syntax across the codebase for CPython 3.14. Remove `from __future__ import annotations`, flatten `Optional`/`Union`/`List`/`Dict` to native forms, adopt `annotationlib`, and apply PEP 758 exception syntax.

## Motivation

Python 3.14 makes `from __future__ import annotations` unnecessary and native union/`| None` syntax is fully standard. Cleaning up legacy typing reduces import noise and aligns with modern Python conventions.

## Deliverables

- Remove `from __future__ import annotations` from all ~50 source files
- `Optional[X]` → `X | None` (~30 files)
- `Union[X, Y]` → `X | Y` (~15 files)
- `List[X]`, `Dict[X,Y]`, `Tuple[...]` from typing → builtins
- `Callable` → `collections.abc.Callable`
- `Iterable` → `collections.abc.Iterable`
- PEP 758: `except (X, Y):` → `except X, Y:` without parens (~50 locations)
- PEP 749: `getattr(func, "__annotations__", {})` → `annotationlib.get_annotations(func)` (2 locations: tools/__init__.py:356, agents/_history.py:207)
- Remove `tomli` fallback imports (3 files)
- Remove `from __future__ import annotations` from test files too

## Acceptance Criteria

- [ ] `ruff check` passes on all changed files
- [ ] `mypy --python-version 3.14` passes on changed files
- [ ] All imports clean (no unused `typing` renames left behind)
- [ ] No `from __future__ import annotations` remains in source or test tree
- [ ] `annotationlib.get_annotations()` used in both documented locations
- [ ] PEP 758 exception syntax applied without regressions

## Dependencies

Parent: [Epic 023](023-epic-py314-modernization.md)

## Estimated Effort

~800 lines, 3–4 hours
