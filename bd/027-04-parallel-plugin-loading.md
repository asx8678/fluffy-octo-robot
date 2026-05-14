---
id: "027-04"
title: "Parallel plugin loading via ThreadPoolExecutor (P1)"
status: closed
epic: "027"
labels: ["performance", "startup", "plugins", "P1"]
created: "2026-06-10"
priority: "P1"
---

## Summary

Plugin discovery and import is currently sequential — 30+ builtin plugins import one at a time, taking ~50-100ms on startup. Use `ThreadPoolExecutor` to import plugins in parallel (~4 worker threads).

## Current Structure (plugins/__init__.py)

```python
def _load_builtin_plugins(plugins_dir, failed_names=None):
    loaded = []
    for item in plugins_dir.iterdir():
        if item.is_dir():
            # ... sequential import via importlib
    return loaded
```

The deferred callback system already supports atomic commit — parallel `register_callback()` calls during parallel imports will be safe once committed atomically after all threads complete.

## Implementation

1. Wrap per-plugin import in a `_import_single_plugin()` function
2. Use `concurrent.futures.ThreadPoolExecutor(max_workers=4)` to map over plugin dirs
3. Collect results (success/failure per plugin)
4. Commit all deferred callbacks atomically after all imports complete
5. Handle partial failures gracefully (log which plugins failed, load the rest)

## Risk

- Python's import lock (`_imp` lock) serializes some import internals, so actual parallelism gains may be limited to ~2x on cold cache
- On warm cache (bytecode cached), imports are I/O bound and parallelism helps more
- Thread safety: plugin `register_callback()` calls are buffered in deferred mode, so no race conditions

## Deliverables

- [ ] `_load_builtin_plugins` uses `ThreadPoolExecutor` for parallel import
- [ ] `_load_user_plugins` also parallelized
- [ ] Deferred commit happens after all threads complete
- [ ] Failed plugin names collected and reported
- [ ] Startup time benchmark shows improvement

## Acceptance Criteria

- [ ] Plugin loading time reduced by 40-60% on cold startup
- [ ] All plugins still load correctly
- [ ] Plugin import failures are reported individually (not lost in thread pool)
- [ ] No race conditions in callback registration
- [ ] All existing tests pass

## Dependencies

Parent: [Epic 027](027-epic-performance-optimization.md)
Depends on: The deferred callback mechanism already exists in `callbacks.py`

## Estimated Effort

~120 lines changed, 4 hours
