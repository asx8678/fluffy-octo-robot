---
id: "025"
title: "Epic: Code Review Remediation — Post-Review Fixes"
status: open
epic: "025"
labels: ["epic", "code-health", "P1", "cleanup", "audit"]
created: "2026-05-18"
priority: "P1"
---

## Summary

Remediation of issues discovered during the systematic code review (2026-05-18). Covers git bloat removal, badge honesty, config module refactoring, circular import resolution, test consolidation, plugin trust UX, Cython compilation strategy, and test isolation hardening.

## Motivation

The review uncovered 8 actionable issues. The generated data artifacts (coverage.json, pre_refactor_hashes.txt) bloat every clone by ~2.5MB. The static CI badges are misleading to potential users. config.py is a 37.7KB god-module handling too many concerns. The circular dependency between config.py and session_storage.py is fragile. Test coverage triplicates waste maintainer time. Plugin trust UX creates a chicken-and-egg problem for first-time users. Cython runtime compilation via pyximport is fragile and slow. Test config isolation uses fragile monkeypatching.

## Deliverables

1. Remove generated data files from git tracking, add to .gitignore
2. Replace static shield.io badges with real dynamic GitHub Actions status badges
3. Refactor config.py: split model config, session config, path config into separate modules
4. Break the config.py ↔ session_storage.py circular dependency
5. Consolidate/remove test coverage triplicates (*_coverage.py, *_extended.py, *_full_coverage.py)
6. Fix plugin trust UX: allow pre-trust via env var or config, or defer plugin loading
7. Replace runtime pyximport compilation with pre-built Cython extension wheels
8. Replace fragile module-level global monkeypatching in conftest.py with proper dependency injection

## Acceptance Criteria

- [ ] coverage.json and pre_refactor_hashes.txt removed from git tracking and added to .gitignore
- [ ] README badges use dynamic GitHub Actions status badge URLs
- [ ] config.py reduced to <15KB by extracting model_config, session_config, path_config modules
- [ ] No circular imports between config modules and session_storage
- [ ] Remaining test files have no *_coverage.py / *_extended.py / *_full_coverage.py patterns
- [ ] Plugin trust can be established via MUSE_TRUST_PLUGIN env var for headless/startup use
- [ ] Cython .so files are pre-built during build, not compiled at import time
- [ ] Test config isolation uses context managers or dependency injection, not global monkeypatching
- [ ] All existing tests pass after each change

## Dependencies

None — self-contained cleanup epic. Does not block other work.

## Estimated Effort

~800 lines changed, 10–16 hours

## Children

- [025-01](025-01-git-bloat.md) — Remove generated data files from git tracking (P1)
- [025-02](025-02-badges.md) — Replace static badges with dynamic CI badges (P1)
- [025-03](025-03-config-god-module.md) — Refactor config.py god-module (P2)
- [025-04](025-04-circular-import.md) — Fix config ↔ session_storage circular import (P2)
- [025-05](025-05-test-consolidation.md) — Consolidate bloated test file triplicates (P2)
- [025-06](025-06-plugin-trust-ux.md) — Fix plugin trust chicken-and-egg at startup (P2)
- [025-07](025-07-cython-build.md) — Replace runtime Cython compilation with pre-built wheels (P3)
- [025-08](025-08-test-isolation.md) — Fix fragile config isolation in conftest.py (P3)
