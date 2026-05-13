---
id: "025-04"
title: "Fix config ↔ session_storage circular import (P2)"
status: open
epic: "025"
labels: ["bug", "architecture", "P2"]
created: "2026-05-18"
priority: "P2"
---

## Summary

Break the fragile bidirectional dependency: `config.py` imports `save_session` from `session_storage.py` at module level, while `session_storage.py` imports `get_config_value` from `config.py` inside function bodies.

## Motivation

Currently avoids deadlock only because `session_storage.py` uses lazy try/except-guarded function-level imports. If `session_storage.py` ever adds a module-level import of config (e.g., for a new decorator or class definition), the application would fail to start with an ImportError. This is a ticking time bomb.

## Solution options

1. **Extract shared paths**: Move path constants (CONFIG_FILE, DATA_DIR, etc.) to a separate `config/paths.py` that has no dependencies on session_storage.
2. **Inversion**: Have session_storage accept config values as parameters rather than importing config.
3. **Lazy import in config.py**: Move config.py's `from code_muse.session_storage import save_session` inside the function that needs it.

## Deliverables

- [ ] Extract paths/constants into dependency-free module
- [ ] Move module-level `from code_muse.session_storage import save_session` out of config.py
- [ ] Remove all lazy try/except function-level imports from session_storage.py
- [ ] Verify no circular import chains exist
- [ ] All existing tests pass

## Dependencies

Parent: [Epic 025](025-epic-code-review-remediation.md)

## Estimated Effort

~50 lines changed, 1–2 hours
