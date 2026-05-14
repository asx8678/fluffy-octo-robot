# Unused / Dead Code Audit Report — `code_muse` Core

**Scope:** Core `code_muse/` modules only. Plugins, tests, and `__pycache__` excluded.  
**Date:** 2026-01-28

---

## 1. Unused / Obsolete Packages (entire directories)

| Package | Files | Status | Notes |
|---------|-------|--------|-------|
| `code_muse/evals/` | 2 files | **UNUSED** | No imports from any core module. Appears to be a standalone evaluation harness that was never wired into the CLI or agent flow. |
| `code_muse/fs_scan_cache/` | 6 files | **UNUSED** | No imports from outside the package. Internal cross-references only. Appears to be a Cython-accelerated file-scan cache that was never integrated. |
| `code_muse/models_cache/` | 7 files | **UNUSED** | No imports from outside the package. `models_dev_parser.py` is imported directly by `command_line/add_model_menu.py`, but the `models_cache/` package itself is never imported. |
| `code_muse/stream_parser/` | 3 files | **UNUSED** | No imports from any core module. Appears to be an SSE stream parser that was never integrated. |

---

## 2. Core `.py` Files with Zero Imports or References

| File | Status | Notes |
|------|--------|-------|
| `code_muse/status_display.py` | **DEAD** | `StatusDisplay` class is defined but never imported or referenced anywhere in the codebase. |
| `code_muse/tools/ask_user_question/demo_tui.py` | **DEAD** | Only referenced in a docstring comment inside itself. Never imported or executed. |

**Note:** Other files flagged by static import analysis (e.g. `hook_engine/*`, `messaging/*`, `agents/*`) are actually consumed via dynamic import patterns (`importlib.import_module`, `pkgutil.iter_modules`) or are imported by plugins outside the core scan scope, so they are **not** dead.

---

## 3. Dynamically-Loaded Agents that are Never Invoked

The agent manager (`agent_manager.py`) discovers every module in `code_muse/agents/` via `pkgutil.iter_modules()`. These agents are **loaded** at runtime but **never selected** by any code path:

| Agent File | Registered Name | Status | Evidence |
|------------|-------------------|--------|----------|
| `code_muse/agents/agent_helios.py` | `helios` | **ORPHANED** | Only referenced in `config_agent.py`'s `UC_AGENT_NAMES` set. No code ever selects `/agent helios` or delegates to it. |
| `code_muse/agents/agent_qa_iris.py` | `qa-iris` | **ORPHANED** | Only referenced in docstring comments (`supervisor_agent.py`, `subagent_console.py`). No code ever selects or delegates to `qa-iris`. |

By contrast, `muse` and `planning-agent` are actively used (fallback default, `/plan` command, config default).

---

## 4. Unused Classes / Functions / Variables within Used Files

These files are imported, but specific definitions inside them are never called:

| File | Unused Symbol | Type | Notes |
|------|---------------|------|-------|
| `code_muse/agents/prompt_v3.py` | `agent_creator_overlay()` | function | Exported but never called by any agent or plugin. |
| `code_muse/agents/_history.py` | `clear_stringify_part_cache()` | function | Defined but never called. |
| `code_muse/agents/_history.py` | `is_tool_result_message()` | function | Defined but never called. |
| `code_muse/agents/_compaction.py` | `_protect_zone_messages()` | function | Defined but never called. |
| `code_muse/messaging/queue_console.py` | `extra_lines`, `theme`, `word_wrap`, `indent_guides`, `max_frames`, `justify`, `markup`, `align` | parameters | Local variables shadow `rich.console.Console` API parameters but are not used in the overridden methods. (Low priority — API compatibility stubs.) |
| `code_muse/command_line/*_completion.py` | `complete_event` | parameter | Unused in multiple completion handlers (API-required callback parameter). (Low priority.) |

---

## 5. Unused Imports

`ruff check --select F401,F821,F841` was run across core modules. **Result: clean** — no unused imports, undefined names, or unused local variables were detected by `ruff` at the core level.

---

## 6. Summary Table — Actionable Removals

| # | Item | Recommended Action | Risk |
|---|------|-------------------|------|
| 1 | `code_muse/evals/` | Remove entire package | Low — completely isolated |
| 2 | `code_muse/fs_scan_cache/` | Remove entire package | Low — no external consumers |
| 3 | `code_muse/models_cache/` | Remove entire package | Low — no external consumers |
| 4 | `code_muse/stream_parser/` | Remove entire package | Low — no external consumers |
| 5 | `code_muse/status_display.py` | Remove file + any stray references | Low — truly dead |
| 6 | `code_muse/tools/ask_user_question/demo_tui.py` | Remove file | Low — demo only |
| 7 | `code_muse/agents/agent_helios.py` | Consider removal or integration | Medium — dynamically loadable but orphaned |
| 8 | `code_muse/agents/agent_qa_iris.py` | Consider removal or integration | Medium — dynamically loadable but orphaned |
| 9 | `agent_creator_overlay()` | Remove function | Low — truly dead |
| 10 | `clear_stringify_part_cache()` | Remove function | Low — truly dead |
| 11 | `is_tool_result_message()` | Remove function | Low — truly dead |
| 12 | `_protect_zone_messages()` | Remove function | Low — truly dead |
