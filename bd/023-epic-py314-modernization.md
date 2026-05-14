---
id: "023"
title: "Epic: CPython 3.14 Modernization — Full-Stack Upgrade"
status: closed
epic: "023"
labels: ["epic", "modernization", "py314", "P0", "breaking"]
created: "2025-07-16"
priority: "P0"
---

## Summary

Upgrade the entire muse codebase to CPython 3.14, adopting all new syntax, stdlib, and async features across six phases. This is a breaking change that drops support for Python <3.14.

## Motivation

CPython 3.14 introduces meaningful improvements: PEP 758 exception grouping syntax, PEP 749 annotationlib, free-threaded builds (PEP 779), t-strings (PEP 750), and a cleaner async/await ecosystem. Staying current reduces technical debt and enables performance gains.

## Deliverables

1. Syntax & Typing Modernization — remove legacy typing, adopt new syntax
2. Async-First Architecture — eliminate blocking calls in async paths
3. Concurrency Model Modernization — InterpreterPoolExecutor, free-threaded readiness
4. Stdlib Upgrades & Path Modernization — pathlib, tomllib, asyncio introspection
5. Cleanup — Deprecated APIs, Ruff & Mypy Rules — py314 targets, strict mypy
6. PEP 750 t-Strings — Investigation & Audit — candidate sites marked, no premature migration

## Acceptance Criteria

- [ ] `from __future__ import annotations` removed from all ~50 source files
- [ ] `Optional[X]` → `X | None`, `Union[X, Y]` → `X | Y`, `List`/`Dict` → builtins
- [ ] `Callable`, `Iterable` moved from `typing` to `collections.abc`
- [ ] PEP 758 `except (X, Y):` → `except X, Y:` applied across ~50 locations
- [ ] PEP 749 `annotationlib.get_annotations()` in 2 locations
- [ ] `tomli` fallback imports removed
- [ ] No `time.sleep` or `requests.*` in async call stacks
- [ ] `subprocess.run` → `asyncio.create_subprocess_exec` where async
- [ ] Blocking `open()` → `aiofiles.open()` in async paths
- [ ] `asyncio.gather(...)` → `asyncio.TaskGroup` + `except*` in 4 locations
- [ ] `os.path` → `pathlib.Path` everywhere (~50 locations)
- [ ] `pyproject.toml` requires-python = ">=3.14,<3.16", ruff target-version = "py314", mypy python_version = "3.14"
- [ ] `ruff check --fix` and `ruff format .` clean across entire codebase
- [ ] `mypy --python-version 3.14 --strict` clean (or documented exceptions)
- [ ] PEP 750 audit complete with TODO markers at ~10-15 candidate sites
- [ ] `uv build` succeeds

## Dependencies

None — this epic is self-contained and blocks no other work.

## Estimated Effort

~3,000 lines touched, 12–16 hours

## Children

- [023-01](023-01-syntax-typing.md) — Phase 1: Syntax & Typing Modernization
- [023-02](023-02-async-architecture.md) — Phase 2: Async-First Architecture
- [023-03](023-03-concurrency-model.md) — Phase 3: Concurrency Model Modernization
- [023-04](023-04-stdlib-pathlib.md) — Phase 4: Stdlib Upgrades & Path Modernization
- [023-05](023-05-cleanup-deprecated.md) — Phase 5: Cleanup — Deprecated APIs, Ruff & Mypy Rules
- [023-06](023-06-tstrings-investigation.md) — Phase 6: PEP 750 t-Strings — Investigation & Audit
