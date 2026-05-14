---
id: "025-03"
title: "Refactor config.py god-module (P2)"
status: closed
epic: "025"
labels: ["refactor", "architecture", "P2"]
created: "2026-05-18"
priority: "P2"
---

## Summary

Split `code_muse/config.py` (37.7 KB, ~1100+ lines) into focused sub-modules covering paths, model config, session config, and security config.

## Motivation

config.py currently handles: XDG directory resolution, config file parsing with caching, model name/agent pinning, session management and autosave, API key loading, file watching, command history, and verbosity settings. This violates the Single Responsibility Principle and makes the module hard to reason about, test, and change.

## Proposed split

- `config/paths.py` — XDG directory resolution, file path constants
- `config/parser.py` — INI config file reading, caching, get/set
- `config/models.py` — model name, agent pinning, context length
- `config/session.py` — autosave, session file management
- `config/security.py` — API key loading (already partially exists as config_security.py)
- `config/__init__.py` — re-exports for backward compatibility

## Deliverables

- [ ] Extract path constants into `config/paths.py`
- [ ] Extract config parser + cache into `config/parser.py`
- [ ] Extract model/agent config into `config/models.py`
- [ ] Extract session/autosave into `config/session.py`
- [ ] Merge `config_security.py` into `config/security.py`
- [ ] Re-export all public symbols from `config/__init__.py` for backward compatibility
- [ ] Update all imports across codebase
- [ ] All existing tests pass

## Dependencies

Parent: [Epic 025](025-epic-code-review-remediation.md)

## Estimated Effort

~400 lines changed, 4–6 hours
