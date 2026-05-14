---
id: "027-07"
title: "Defer models.json reading to first model resolution (P2)"
status: closed
epic: "027"
labels: ["performance", "startup", "P2"]
created: "2026-06-10"
priority: "P2"
---

## Note

After investigation, `ModelFactory.load_config()` already has a working fingerprint-based cache (`_models_config_cache`). It does NOT read the 535KB `models_dev_api.json` — only `models.json` (~few KB). The `cli_runner/__init__.py` eagerly calls `load_config()` at line 182 for model validation, which is a one-time read. This issue was based on a misunderstanding; the code is already optimized.

## Summary

`model_factory.py::ModelFactory.load_config()` reads `models.json` and `models_dev_api.json` (535 KB!) eagerly on startup via `ensure_config_exists()` → model resolution chain. Defer to first actual model resolution.

## Current Flow

1. `main.py` → `load_plugin_callbacks()` → `on_startup()` callbacks fire
2. Some startup callbacks call `ModelFactory.get_model()` which calls `load_config()`
3. `load_config()` reads and parses 535 KB `models_dev_api.json` + `models.json`
4. This happens even if the user never changes models

## Fix

1. Make `ModelFactory.load_config()` use the existing `get_cached_models_config()` from `summarization_agent.py` (which already has mtime-based caching)
2. Or: add a `_config: dict | None = None` class variable to `ModelFactory`, populated on first `get_model()` call, not at import time
3. Ensure `set_config_value()` invalidates the cached config

## Deliverables

- [ ] `ModelFactory.load_config()` returns cached config (empty on first call)
- [ ] Config loaded lazily on first model resolution
- [ ] Config invalidated when user changes model settings
- [ ] Startup time benchmark shows improvement

## Acceptance Criteria

- [ ] `models_dev_api.json` (535 KB) not read during startup
- [ ] First model resolution still correctly loads and parses config
- [ ] Config changes (model add, remove, edit) propagate correctly
- [ ] All tests pass

## Dependencies

Parent: [Epic 027](027-epic-performance-optimization.md)
Related: `summarization_agent.py` already has `get_cached_models_config()` — reuse pattern

## Estimated Effort

~100 lines changed, 1 day (careful — many callers depend on load_config behavior)
