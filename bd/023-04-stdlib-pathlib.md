---
id: "023-04"
title: "Phase 4: Stdlib Upgrades & Path Modernization"
status: closed
epic: "023"
labels: ["modernization", "py314", "stdlib", "pathlib", "P1"]
created: "2025-07-16"
priority: "P1"
---

## Summary

Replace all `os.path` usage with `pathlib.Path`, drop `tomli` fallbacks for the built-in `tomllib`, and optionally adopt new 3.14 stdlib features like `compression.zstd` and asyncio introspection APIs.

## Motivation

`pathlib` is the modern, object-oriented path API. Python 3.14 solidifies `tomllib` as the standard TOML reader (no fallback needed). These changes reduce imports and improve cross-platform path handling.

## Deliverables

- `os.path` → `pathlib.Path` everywhere (~50 locations in config.py, error_logging.py, command_line/*.py, messaging/rich_renderer.py, http_utils.py)
- Remove `tomli` fallback in 3 files (just `import tomllib`)
- Optional: PEP 784 `compression.zstd` (no current gzip/bz2 usage — skip)
- `asyncio` introspection APIs for debugging (optional enhancement)

## Acceptance Criteria

- [ ] No `os.path` imports remain in the codebase
- [ ] `ruff` rule PLW1514 passes (no `os.path` usage)
- [ ] All path operations use `pathlib.Path` idioms
- [ ] `tomllib` used directly, `tomli` fallback removed
- [ ] Optional: `compression.zstd` evaluated and documented if skipped

## Dependencies

Parent: [Epic 023](023-epic-py314-modernization.md)

## Estimated Effort

~500 lines, 2–3 hours
