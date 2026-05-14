---
id: "027-03"
title: "Cache sorted callback lists with fast-path (P1)"
status: closed
epic: "027"
labels: ["performance", "callbacks", "P1"]
created: "2026-06-10"
priority: "P1"
---

## Summary

`get_callbacks()` sorts by priority on **every** dispatch. With ~30 hook phases and callbacks triggered hundreds of times per agent run, this creates measurable overhead. Fix: maintain pre-sorted cache, update only on registration/removal.

## Current Code (callbacks.py)

```python
def get_callbacks(phase: PhaseType) -> list[CallbackFunc]:
    callbacks = _callbacks.get(phase, [])
    sorted_callbacks = sorted(callbacks, key=lambda item: item[0], reverse=True)
    return [func for _priority, func in sorted_callbacks]  # Sorted EVERY time
```

Also, most `on_*` functions check `if not callbacks:` AFTER the sort has already happened.

## Fix

1. Add `_sorted_cache: dict[PhaseType, list[CallbackFunc]]` to callbacks module
2. Invalidate relevant cache entry on `register_callback()` and `unregister_callback()`
3. In `get_callbacks()`: return `_sorted_cache.get(phase, [])` — no sort
4. Replace `sorted(callbacks, key=lambda ...)` with `sorted(..., key=itemgetter(0))` in the one registration path
5. Add fast-path guard at the top of every `on_*` function: `if not _callbacks.get("startup", []): return []`

## Deliverables

- [ ] `_sorted_cache` dict maintained with lazy rebuild on registration change
- [ ] `get_callbacks()` returns cached sorted list
- [ ] Every `on_*` function has empty-list fast-path guard
- [ ] All callback tests pass

## Acceptance Criteria

- [ ] `get_callbacks()` does NOT call `sorted()` on hot path
- [ ] Callback order (priority descending) is preserved
- [ ] Empty hook phases return immediately without list construction
- [ ] No test regressions

## Dependencies

Parent: [Epic 027](027-epic-performance-optimization.md)

## Estimated Effort

~100 lines changed, 4 hours
