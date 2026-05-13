---
id: "024-10"
title: "get_verbosity: Remove sys.argv Scan (P1)"
status: closed
epic: "024"
labels: ["bug", "verbosity", "P1", "correctness"]
created: "2026-05-18"
closed: "2026-05-18"
priority: "P1"
---

## Summary

**Finding 1.7:** `get_verbosity()` in `verbosity.py` parsed `-u`, `-v`, `-vv`, `-vvv` by literal membership in `sys.argv`. Any user prompt, file path, or model name containing `-v` or `-vv` as a standalone token would set the verbosity level for the entire process.

**Fix:** Removed `sys.argv` scan. Added module-level `_verbosity_override` set by CLI via `set_verbosity()` after argparse. Resolution order: explicit arg → CLI override → env var → COMPACT default.

## What

Refactor `get_verbosity()` to accept an optional `verbosity: int | None` parameter. If provided, return it directly. Update CLI argparse to capture `-v`/`-vv`/`-vvv` and pass the parsed level into `get_verbosity()`. Remove all `sys.argv` iteration and string-matching logic from `verbosity.py`.

## Deliverables

- [x] `get_verbosity()` accepts optional verbosity argument
- [x] CLI sets verbosity after `argparse` in `cli_runner/args.py`
- [x] `sys.argv` scan removed from `verbosity.py`
- [x] `ruff check` passes on changed files
- [x] All existing callers (`dispatcher.py`, `build_filter`, `shell_minimizer`) unchanged — backward compatible

## Acceptance Criteria

- [x] `-p "review -v output"` does NOT set VERBOSE mode globally
- [x] `--verbose` counts correctly set verbosity levels (1→VERBOSE, 2→VERY_VERBOSE, 3+→RAW)
- [x] `--ultra-compact` / `-u` sets ULTRA_COMPACT level
- [x] `FAST_PUPPY_VERBOSITY=2` env var still works
- [x] Tests confirm: default COMPACT, stray `-v` ignored, override works

## Dependencies

Parent: [Epic 024](024-epic-code-health.md)

## Estimated Effort

~40 lines changed, 30 minutes
