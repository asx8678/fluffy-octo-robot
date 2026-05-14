---
id: "027-01"
title: "Replace stdlib json with orjson across all files (P0)"
status: closed
epic: "027"
labels: ["performance", "library-swap", "P0"]
created: "2026-06-10"
priority: "P0"
---

## Summary

Replace all 53 `import json` usages with `import orjson as json`. The project already depends on `orjson` in `pyproject.toml` but only uses it in `agents/_history.py`. Every other file uses stdlib `json` which is 3-5x slower for serialization and 4x slower for deserialization.

## Motivation

`orjson` is already a dependency. Using it consistently provides:
- **3-5x faster** `dumps()` (uses Rust FFI)
- **4x faster** `loads()` 
- **Native support** for `bytes`, `datetime`, `UUID`, `Path`, `dataclass` serialization
- Already battle-tested in `_history.py` and `smartcrusher` plugins

## API Compatibility

`orjson.dumps()` returns `bytes` not `str` — this is the main API difference. Most callers `json.loads()` a string, process, and `json.dumps()` back. The bytes return type requires:
- `json.dumps(data).decode()` in string contexts (or use `orjson.dumps(data).decode()`)
- Some callers use `json.dumps(data, indent=2)` — `orjson` supports `option=orjson.OPT_INDENT_2`

## Files to Change

Critical hot path (highest priority):
- `session_storage_helpers.py` — session save/load (every session op)
- `session_storage.py` — session persistence
- `plugins/__init__.py` — trust manifest read/write (every plugin load)
- `model_factory.py` — models.json (every model resolution)
- `command_line/config_commands.py` — config export
- `tools/file_modifications.py` — diff operations
- `models_cache/cache_writer.py` — model cache writes
- `agents/agent_manager.py` — agent config serialization
- `agents/_history.py` — ALREADY USING orjson

Secondary (still beneficial):
- All 44 remaining `import json` files in plugins, tools, command_line, etc.

## Deliverables

- [ ] Systematically replace `import json` → `import orjson as json` across all 53 files
- [ ] Fix `json.dumps()` → `.decode()` pattern where return bytes matters
- [ ] Replace `json.dumps(data, indent=2)` → `orjson.dumps(data, option=orjson.OPT_INDENT_2).decode()`
- [ ] Handle `json.dumps(data, sort_keys=True)` → `orjson.dumps(data, option=orjson.OPT_SORT_KEYS)`
- [ ] `ruff check --fix` + `ruff format` on all changed files
- [ ] All tests pass

## Files to Change

`code_muse/session_storage_helpers.py`, `code_muse/session_storage.py`, `code_muse/plugins/__init__.py`, `code_muse/model_factory.py`, `code_muse/command_line/config_commands.py`, `code_muse/tools/file_modifications.py`, `code_muse/models_cache/cache_writer.py`, `code_muse/agents/agent_manager.py`, plus ~45 other files with `import json`.

## Acceptance Criteria

- [ ] All 53 stdlib `json` imports eliminated from `code_muse/`
- [ ] `orjson` benchmark confirms 3-5x speedup on hot-path serialization
- [ ] All session save/load tests pass
- [ ] Plugin trust manifest round-trips correctly
- [ ] Model config loading works
- [ ] No regression in any tool that processes JSON

## Dependencies

Parent: [Epic 027](027-epic-performance-optimization.md)

## Estimated Effort

~300 lines changed, 1 day (mostly mechanical find/replace with careful API audit)
