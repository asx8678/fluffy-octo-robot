---
id: "027-06"
title: "Audit and switch to asyncio.Lock in async-only paths (P2)"
status: closed
epic: "027"
labels: ["performance", "concurrency", "free-threading", "P2"]
created: "2026-06-10"
priority: "P2"
---

## Note

Audit complete. All `threading.Lock` usages are correct for their access patterns. No code changes needed.

## Summary

The codebase consistently uses `threading.Lock` with `# FREE-THREADED` comments. However, some paths are **only accessed from async code** and could use `asyncio.Lock` instead, avoiding OS-level futex calls.

## Why asyncio.Lock Is Faster

- `threading.Lock` acquires an OS mutex (futex syscall) even in single-threaded async code
- `asyncio.Lock` is a user-space coroutine yield — no syscall, no GIL/thread overhead
- Python 3.14's free-threading mode doesn't change this: if the data is ONLY accessed from one thread's async tasks, `asyncio.Lock` is still cheaper

## Files to Audit

| File | Lock | Access Pattern | Safe to Change? |
|------|------|---------------|-----------------|
| `messaging/bus.py` `_lock` | `threading.Lock` | `_pending_requests` (async only), `_current_session_id` (async only), `_startup_buffer` (async + sync emit) | **No** — sync callers exist |
| `summarization_agent.py` `_summarization_loop_lock` | `threading.Lock` | Guards event loop creation; accessed from thread pool worker | **No** — cross-thread |
| `summarization_agent.py` `_models_config_lock` | `threading.Lock` | Guards config cache; called from thread pool worker | **No** — cross-thread |
| `summarization_agent.py` `_agent_lock` | `threading.Lock` | Agent cache | **No** — thread pool |
| `config/parser.py` `_config_cache_lock` | `threading.Lock` | Config cache; called from sync code | **No** — sync callers |
| `fs_scan_cache/scan_cache_core.pyx` `_lock` | `threading.Lock` | LRU cache; documented as sync/async crossover | **No** — already correct |
| `plugins/__init__.py` `_plugin_hash_cache` | None (dict access) | Read during startup only | No lock needed |

## Conclusion

After audit: **all threading.Lock usages are correct**. The async-only paths in `MessageBus._pending_requests` are protected by the same lock as `_startup_buffer` which has sync callers. No changes needed, but document the audit findings.

## Deliverables

- [ ] Systematic audit of all `threading.Lock` usages (list in this issue)
- [ ] For any `async-only` candidates found: switch to `asyncio.Lock`
- [ ] Document rationale for locks that must remain `threading.Lock`
- [ ] All tests pass

## Acceptance Criteria

- [ ] All `threading.Lock` usages documented with justification or changed to `asyncio.Lock`
- [ ] No regressions in any concurrency-sensitive code path
- [ ] Free-threaded Python 3.14 compatibility preserved

## Dependencies

Parent: [Epic 027](027-epic-performance-optimization.md)

## Estimated Effort

~80 lines changed (mostly audit comments), 4 hours
