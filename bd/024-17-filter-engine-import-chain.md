---
id: "024-17"
title: "filter_engine __init__.py: Explicit Import Chain (P2)"
status: closed
epic: "024"
labels: ["cleanup", "imports", "P2", "coupling"]
created: "2026-05-18"
priority: "P2"
---

## Summary

Finding 2.4 — `__init__.py` imports `{code, git, lint, test}` but omits `ast_compressor`, `ast_parser`, `json_compressor`, `json_patterns`. Invisible coupling via transitive imports. Fix: explicitly import all strategy submodules.

## What

Add explicit imports for `ast_compressor`, `ast_parser`, `json_compressor`, `json_patterns` to `filter_engine/__init__.py`. Re-export symbols so downstream code does not rely on transitive import chains.

## Deliverables

- [ ] All strategy submodules explicitly imported
- [ ] Tests pass

## Acceptance Criteria

- [ ] `filter_engine/__init__.py` imports every strategy submodule explicitly
- [ ] No downstream breakage from transitive import removal
- [ ] `ruff check` passes
- [ ] All tests pass

## Dependencies

Parent: [Epic 024](024-epic-code-health.md)

## Estimated Effort

~20 lines changed, 15 minutes
