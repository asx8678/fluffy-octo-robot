---
id: "025-07"
title: "Replace runtime Cython compilation with pre-built wheels (P3)"
status: open
epic: "025"
labels: ["build", "performance", "P3"]
created: "2026-05-18"
priority: "P3"
---

## Summary

Replace runtime `pyximport.install()` compilation of `.pyx` files with pre-built Cython extension modules shipped as part of the wheel distribution.

## Motivation

Currently, `code_muse/__init__.py` calls `pyximport.install()` which compiles all `.pyx` files on first import. This:
- Requires a C compiler at runtime (not guaranteed on all platforms)
- Slows first import significantly (several seconds)
- Can fail silently or produce cryptic errors on systems without a C compiler
- Writes compiled artifacts into the package directory (side effect)
- Breaks under some deployment scenarios (container images, read-only filesystems)

## Solution

Use `hatchling`'s build hooks to compile `.pyx` files during `uv build` / `pip wheel`, shipping pre-built `.so`/`.pyd` files in the wheel. At runtime, import the compiled extensions normally without pyximport.

## Deliverables

- [ ] Add `cython` as a build dependency in `pyproject.toml` (`[build-system] requires`)
- [ ] Remove `pyximport` dependency and `pyximport.install()` call from `__init__.py`
- [ ] Remove `_rebuild_stale_cython_modules()` function
- [ ] Remove `CYTHON_ENABLED` / `PYX_MODULE_COUNT` globals (or make them detect pre-built .so files)
- [ ] Configure hatchling build hooks to compile .pyx → .so during build
- [ ] Verify `uv build` produces wheels with compiled extensions
- [ ] Verify `uv run` works without C compiler
- [ ] All existing tests pass

## Dependencies

Parent: [Epic 025](025-epic-code-review-remediation.md)

## Estimated Effort

~80 lines changed, 2–3 hours
