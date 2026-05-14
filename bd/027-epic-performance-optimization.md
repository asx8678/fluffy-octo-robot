---
id: "027"
title: "Epic: Performance Optimization — Library Swaps, Callback System & Startup Time"
status: open
epic: "027"
labels: ["epic", "performance", "P0"]
created: "2026-06-10"
priority: "P0"
---

## Summary

Comprehensive performance optimization based on deep codebase review (2026-06-10). Covers 9 targeted improvements across library swaps, callback dispatch efficiency, startup time reduction, concurrency patterns, and AST compression completeness.

The codebase is already heavily Cython-optimized (14 .pyx files) with well-designed LRU caches and efficient data structures. These remaining opportunities target **consistent library usage**, **reducing per-dispatch overhead**, **parallelizing startup**, and **closing the last few Cython coverage gaps**.

## Source

Review by `planning-agent-e48180` (2026-06-10) — deep codebase analysis covering all 63 modules, dependency graph, and hot-path profiling.

## Deliverables

1. Replace all `import json` with `import orjson as json` (compatible API) across 53 files
2. Pre-compile regex patterns in shell_minimizer primitives at pipeline build time
3. Cache sorted callback lists; add empty-list fast-path to all on_* functions
4. Parallelize plugin loading with ThreadPoolExecutor
5. Move token estimation after dirty-flag check in session_storage
6. Audit and switch to asyncio.Lock in async-only paths
7. Defer models.json reading from startup to first model resolution
8. Message pool for frequently-emitted message types
9. Extend _walk_cython to JavaScript/Go/Rust/C++ compressors

## Acceptance Criteria

- [ ] All stdlib `json` imports replaced with `orjson`; `orjson.dumps` used across all hot paths
- [ ] Regex patterns in `shell_minimizer/primitives.py` pre-compiled at pipeline build time
- [ ] Callback dispatch uses pre-sorted cached lists; all `on_*` functions have empty-list fast-path
- [ ] Plugin loading uses `ThreadPoolExecutor` for parallel discovery
- [ ] Token estimation moved after dirty-flag check in `session_storage.py`
- [ ] `asyncio.Lock` used in paths verified as async-only; `threading.Lock` retained for sync/async crossover
- [ ] `models.json` read deferred from startup to first model resolution
- [ ] `MessageBus.emit` uses pooled message templates for frequent types
- [ ] JavaScript/Go/Rust/C++ AST walkers use Cython `_walk_cython` instead of pure Python recursion
- [ ] All existing tests pass

## Dependencies

Epic 026 (findings remediation) should be closed first to avoid merge conflicts in shared files.

## Estimated Effort

~800 lines changed, 3–5 days total

## Children

- [027-01](027-01-json-to-orjson.md) — Replace stdlib `json` with `orjson` across all files (P0)
- [027-02](027-02-precompile-regex-primitives.md) — Pre-compile regex in shell_minimizer primitives (P0)
- [027-03](027-03-cached-sorted-callbacks.md) — Cache sorted callback lists with fast-path (P1)
- [027-04](027-04-parallel-plugin-loading.md) — Parallel plugin loading via ThreadPoolExecutor (P1)
- [027-05](027-05-token-estimation-after-dirty-flag.md) — Move token estimation after dirty-flag check (P2)
- [027-06](027-06-asyncio-lock-audit.md) — Audit and switch to asyncio.Lock in async-only paths (P2)
- [027-07](027-07-deferred-models-json.md) — Defer models.json reading to first model resolution (P2)
- [027-08](027-08-message-pool.md) — Message pool for frequently-emitted message types (P3)
- [027-09](027-09-walk-cython-extensions.md) — Extend `_walk_cython` to JS/Go/Rust/C++ compressors (P3)
