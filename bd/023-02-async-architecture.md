---
id: "023-02"
title: "Phase 2: Async-First Architecture"
status: closed
epic: "023"
labels: ["modernization", "py314", "async", "P0"]
created: "2025-07-16"
priority: "P0"
---

## Summary

Eliminate blocking I/O and sync calls from all async code paths. Replace `time.sleep`, `requests`, `subprocess.run`, blocking `open()`, and `socket` checks with their async equivalents, and migrate `asyncio.gather` to `asyncio.TaskGroup`.

## Motivation

Blocking calls in async functions starve the event loop, causing latency spikes and poor concurrency. Python 3.14’s mature `asyncio` ecosystem (httpx, aiofiles, TaskGroup) makes a fully async architecture practical.

## Deliverables

- `time.sleep` → `await asyncio.sleep` in async contexts (~15 locations)
- `requests.get/post` → `httpx.AsyncClient` (~12 locations)
- `subprocess.run` → `await asyncio.create_subprocess_exec` (~20 locations)
- Blocking file `open()` → `aiofiles.open()` in async paths
- `socket.socket` port check → async equivalent
- `asyncio.gather(*tasks, return_exceptions=True)` → `asyncio.TaskGroup` + `except*` (4 locations)
- Mark remaining unavoidable blocking calls with `await asyncio.to_thread(...)` + TODO

## Acceptance Criteria

- [ ] All async tests pass
- [ ] No `time.sleep` remains in any async call stack
- [ ] No `requests.*` remains in any async call stack
- [ ] `subprocess.run` only used in intentionally sync paths
- [ ] `asyncio.TaskGroup` used in all 4 identified locations
- [ ] Unavoidable blocking calls wrapped in `asyncio.to_thread` with TODO comment

## Dependencies

Parent: [Epic 023](023-epic-py314-modernization.md)

## Estimated Effort

~900 lines, 4–5 hours
