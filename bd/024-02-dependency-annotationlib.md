---
id: "024-02"
title: "Missing annotationlib Dependency Resolution (P0)"
status: closed
epic: "024"
labels: ["bug", "dependency", "P0", "import-error"]
created: "2026-05-18"
priority: "P0"
---

## Summary

`annotationlib` is imported in 2 core files (`code_muse/agents/_history.py:17` and `code_muse/tools/__init__.py:1`) but is **not** listed in `pyproject.toml` dependencies. Without it, the application crashes at import time.

## Usage Locations

| File | Line | Import |
|------|------|--------|
| `code_muse/agents/_history.py` | 17 | `from annotationlib import get_annotations` |
| `code_muse/agents/_history.py` | 206 | `annotations = get_annotations(tool_func)` |
| `code_muse/tools/__init__.py` | 1 | `from annotationlib import get_annotations` |
| `code_muse/tools/__init__.py` | 358 | `annotations = get_annotations(func).copy()` |

## Deliverables

- [ ] Determine the actual Python 3.14 module name for PEP 749 annotation introspection
- [ ] If `annotationlib` exists: ensure it's covered by Python stdlib in the target version range
- [ ] If NOT available: implement fallback shim `_get_annotations(func)` using `getattr(func, "__annotations__", {})`
- [ ] Replace both import sites with the resolved import
- [ ] Verify the application starts without ImportError

## Acceptance Criteria

- [ ] `python -c "from code_muse.agents._history import stringify_part; print('OK')"` succeeds
- [ ] `python -c "from code_muse.tools import TOOL_REGISTRY; print('OK')"` succeeds
- [ ] `ruff check` passes on changed files
- [ ] All existing tests pass

## Dependencies

Parent: [Epic 024](024-epic-code-health.md)

## Estimated Effort

~30 lines changed, 45 minutes (including investigation)
