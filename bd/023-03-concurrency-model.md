---
id: "023-03"
title: "Phase 3: Concurrency Model Modernization"
status: closed
epic: "023"
labels: ["modernization", "py314", "concurrency", "P1"]
created: "2025-07-16"
priority: "P1"
---

## Summary

Audit and modernize concurrency primitives for Python 3.14. Convert sync locks/events to async equivalents where appropriate, adopt `concurrent.interpreters.InterpreterPoolExecutor` for isolated execution, and document free-threaded (PEP 779) readiness.

## Motivation

Python 3.14 ships with free-threaded builds and `concurrent.interpreters` as a stable alternative to `multiprocessing` for CPU-bound isolation. Preparing the codebase now avoids a future migration rush.

## Deliverables

- Audit `threading.Lock` usage — convert I/O-protecting locks to `asyncio.Lock` where in async paths
- `multiprocessing.Process` → `concurrent.interpreters.InterpreterPoolExecutor` (1 file: plugins/universal_constructor/runner.py)
- `concurrent.futures.ThreadPoolExecutor` → add free-threaded readiness annotations
- `threading.Event` → `asyncio.Event` for async signaling paths
- Document free-threaded (PEP 779) readiness

## Acceptance Criteria

- [ ] `test_universal_constructor.py` passes with new interpreter pool
- [ ] `test_command_runner_coverage.py` passes
- [ ] `test_round_robin_thread_safety.py` passes
- [ ] All async paths use `asyncio.Lock`/`asyncio.Event` where applicable
- [ ] Free-threaded readiness documented in relevant module docstrings

## Dependencies

Parent: [Epic 023](023-epic-py314-modernization.md)

## Estimated Effort

~400 lines, 2–3 hours
