---
id: "025-08"
title: "Fix fragile config isolation in conftest.py (P3)"
status: open
epic: "025"
labels: ["tests", "reliability", "P3"]
created: "2026-05-18"
priority: "P3"
---

## Summary

Replace the fragile monkeypatching of `cp_config.CONFIG_FILE` and `cp_config.CONFIG_DIR` module-level globals in `tests/conftest.py` with a proper context manager or dependency injection approach.

## Motivation

The current `isolate_config_between_tests` fixture monkeypatches module-level globals:
```python
cp_config.CONFIG_FILE = temp_config_file
cp_config.CONFIG_DIR = temp_config_dir
```

This is fragile because:
- If any test module imports from `config.py` at module level before the fixture runs, the monkeypatch is too late
- Changes to `config.py` that add new module-level path references may silently bypass the isolation
- The fixture must carefully restore original values in `yield` cleanup
- xdist worker isolation works only by coincidence (separate processes)

## Solution

Add a `set_config_paths()` function to `config.py` (or a test helper) that cleanly replaces the path objects, with an optional context manager API:

```python
with isolated_config(tmp_path):
    # config now reads from temp paths
    ...
# config restored automatically
```

## Deliverables

- [ ] Add context manager API for config path isolation in `config.py` or `conftest.py`
- [ ] Replace monkeypatching in `conftest.py` with context manager
- [ ] Add test that verifies isolation works even if config is imported early
- [ ] All existing tests pass

## Dependencies

Parent: [Epic 025](025-epic-code-review-remediation.md)

## Estimated Effort

~50 lines changed, 1 hour
