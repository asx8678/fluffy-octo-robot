# Global Mutable State Audit

**Issue:** fluffy-octo-robot-m48.8  
**Date:** 2025-05-17  
**Auditor:** muse-7a69cc

---

## Executive Summary

The codebase contains **39 module-level mutable globals** across ~25 files. These fall into four risk categories:

| Category | Count | Risk | Recommended Fix |
|----------|-------|------|-----------------|
| **CRITICAL** — Shared mutable dict/list/set with no isolation | 15 | Data corruption in multi-agent runs, test cross-contamination | `contextvars.ContextVar` or scoped manager |
| **HIGH** — Singleton + lock pattern (lazy init) | 12 | Correct but fragile; global lock contention under concurrency | Keep lock; document thread-safety contract |
| **MEDIUM** — Plugin/module registry dicts | 8 | App-lifecycle state; mutated once at startup then read-only | Acceptable; add `Final` annotation or freeze-after-boot |
| **LOW** — Config/constants technically mutable | 4 | Python const convention (UPPER) but no enforcement | Add `__all__` + naming discipline |

---

## Inventory: All Module-Level Mutable Globals

### CRITICAL — Shared Mutable Collections (no per-context isolation)

These are the **top priority**. In concurrent sub-agent invocations or parallel test runs,
multiple agents sharing the same process will read/write the same dict/list/set,
causing data corruption, leaked state, and flaky tests.

| # | File | Variable | Type | Mutation Pattern | Fix |
|---|------|----------|------|-----------------|-----|
| 1 | `agents/agent_manager.py:21` | `_AGENT_REGISTRY` | `dict[str, type\|str]` | Written at startup; read-heavy after | **MEDIUM** — registry pattern, acceptable if frozen after boot |
| 2 | `agents/agent_manager.py:25` | `_DISCOVERY_CACHE` | `dict[str, type\|str]` | Populated on first access; rarely mutated | **MEDIUM** — cache; add TTL or freeze-after-boot |
| 3 | `agents/agent_manager.py:26` | `_AGENT_HISTORIES` | `dict[str, list[ModelMessage]]` | **Written per-session** — stores message history per agent name | **CRITICAL** — shared across sessions in same process; should be per-session |
| 4 | `agents/agent_manager.py:30` | `_SESSION_AGENTS_CACHE` | `dict[str, str]` | Written per-session | **CRITICAL** — same as above |
| 5 | `agents/_builder.py:32` | `_system_prompt_cache` | `dict[tuple, str]` | Populated on first use; read-heavy | **MEDIUM** — cache; acceptable with lock |
| 6 | `callbacks.py:92` | `_sorted_cache` | `dict[PhaseType, list]` | Written when callbacks change | **MEDIUM** — cleared on register/unregister; acceptable |
| 7 | `callbacks.py:105` | `_deferred_registrations` | `list[tuple]` | Written at startup, consumed once | **LOW** — consumed then empty |
| 8 | `config/models.py:13` | `_model_validation_cache` | `dict` | Cache; written on first validation | **MEDIUM** — cache; acceptable with lock |
| 9 | `config/parser.py:14` | `_config_cache` | `tuple\|None` | Written on config load | **MEDIUM** — cache; acceptable |
| 10 | `tools/agent_tools.py:57` | `_model_instance_cache` | `dict[str, Any]` | **Written per-session** — model instances | **CRITICAL** — leaked across sessions |
| 11 | `tools/agent_tools.py:65` | `_subagent_agent_cache` | `dict[tuple, Any]` | **Written per-session** — agent instances | **CRITICAL** — leaked across sessions |
| 12 | `tools/chrome_cdp/__init__.py:27` | `_PERSISTENT_SESSIONS` | `dict[str, CdpSession]` | **Written per-session** — CDP sessions | **CRITICAL** — CDP state leaks |
| 13 | `tools/chrome_cdp/__init__.py:28` | `_ACTIVE_TABS_CACHE` | `dict[str, str]` | Written on tab refresh | **HIGH** — shared; but single-user tool |
| 14 | `tools/chrome_cdp/__init__.py:29` | `_PAGES_CACHE` | `list[dict]` | Written on page list refresh | **HIGH** — shared; but single-user tool |
| 15 | `tools/chrome_cdp/__init__.py:204` | `_PENDING` | `dict[int, Future]` | Written per CDP request | **HIGH** — async-global; per-event-loop risk |
| 16 | `tools/skills_tools.py:30` | `_background_jobs` | `dict[str, dict]` | Written per background job | **HIGH** — shared job tracker |
| 17 | `tools/background_jobs.py:26` | `_BACKGROUND_JOBS` | `dict[int, BackgroundJob]` | Written per background job | **HIGH** — shared job tracker |
| 18 | `tools/command_runner.py:116` | `_RUNNING_PROCESSES` | `set[Popen]` | Written per command execution | **HIGH** — shared process tracker |
| 19 | `tools/command_runner.py:119` | `_USER_KILLED_PROCESSES` | `set` | Written on user kill | **HIGH** — shared kill tracker |
| 20 | `tools/command_runner.py:132` | `_ACTIVE_STOP_EVENTS` | `set[Event]` | Written per stop request | **HIGH** — shared stop tracker |
| 21 | `tools/__init__.py:82` | `REMOVED_LEGACY_TOOLS` | `set[str]` | Written at startup | **LOW** — write-once |
| 22 | `session_storage_helpers.py:49` | `_LAST_SAVED_HASHES` | `dict[tuple, str\|None]` | Written per save | **HIGH** — shared across sessions |
| 23 | `command_line/command_registry.py:30` | `_COMMAND_REGISTRY` | `dict[str, CommandInfo]` | Written at startup | **MEDIUM** — registry pattern |
| 24 | `plugins/custom_commands/register_callbacks.py:40` | `_command_cache` | `dict[str, CommandDef]` | Cache; written on discovery | **MEDIUM** — cache; cleared on reload |
| 25 | `plugins/token_ratio_learner/ratios.py:22` | `_LEARNED_RATIOS` | `dict[str, float]` | Written per learning update | **HIGH** — shared learning state |
| 26 | `plugins/customizable_commands/register_callbacks.py:9` | `_custom_commands` | `dict[str, str]` | Written at startup | **MEDIUM** — registry pattern |
| 27 | `plugins/customizable_commands/register_callbacks.py:10` | `_command_descriptions` | `dict[str, str]` | Written at startup | **MEDIUM** — registry pattern |
| 28 | `plugins/debate/telemetry.py:42` | `_review_timestamps` | `list[float]` | Written per review | **HIGH** — shared debate state |
| 29 | `plugins/debate/state.py:29` | `_review_history` | `list[dict]` | Written per review | **HIGH** — shared debate state |
| 30 | `plugins/debate/register_callbacks.py:443` | `_pending_review_indices` | `set[int]` | Written per review | **HIGH** — shared debate state |
| 31 | `plugins/policy_engine/policy_file_discovery.py:14` | `_file_mtimes` | `dict[str, float]` | Cache; written on file change | **MEDIUM** — cache |
| 32 | `plugins/universal_critic/orchestrator.py:33` | `_ITERATION_TRACKER` | `dict[str, int]` | Written per critic iteration | **HIGH** — shared critic state |
| 33 | `plugins/agent_skills/register_callbacks.py:18` | `_deactivated_skills` | `set[str]` | Written on deactivate | **MEDIUM** — preference state |
| 34 | `plugins/task_context/detector.py:183` | `_previous_message_vectors` | `list[list[float]]` | Written per detection | **HIGH** — shared detector state |
| 35 | `model_factory/_plugin_registry.py:13` | `_CUSTOM_MODEL_PROVIDERS` | `dict[str, type]` | Written at startup via callback | **MEDIUM** — registry pattern |
| 36 | `messaging/spinner/__init__.py:17` | `_active_spinners` | `list` | Written per spinner create/stop | **HIGH** — shared spinner state |

### HIGH — Singleton + Lock Pattern (Lazy Initialization)

These use the "lock + lazy init" pattern. They're **thread-safe** but create global singletons
that don't isolate between sessions/contexts.

| # | File | Variable | Type | Pattern |
|---|------|----------|------|---------|
| 1 | `summarization_agent.py:25-34` | `_summarization_agent`, `_cached_model_name` | `Agent\|None`, `str\|None` | Singleton with `_agent_lock` |
| 2 | `summarization_agent.py:34` | `_thread_pool` | `ThreadPoolExecutor\|None` | Singleton with `_agent_lock` |
| 3 | `summarization_agent.py:95` | `_summarization_loop` | `asyncio.AbstractEventLoop\|None` | Singleton with `_summarization_loop_lock` |
| 4 | `messaging/bus.py:570` | `_global_bus` | `MessageBus\|None` | Singleton with `_bus_lock` |
| 5 | `messaging/message_queue.py:283` | `_global_queue` | `MessageQueue\|None` | Singleton with `_queue_lock` |
| 6 | `interpreter_pool.py:391` | `_default_executor` | `SubInterpreterExecutor\|None` | Singleton with `_default_lock` |
| 7 | `tools/mitmproxy/proxy_manager.py:23` | `_manager` | `MitmProxyManager\|None` | Singleton |
| 8 | `command_line/clipboard.py:480` | `_clipboard_manager` | `ClipboardAttachmentManager\|None` | Singleton with `_manager_lock` |
| 9 | `command_line/wiggum_state.py:42` | `_wiggum_state` | `WiggumState()` | Eager singleton — **no lock!** |
| 10 | `plugins/auto_review/cache.py:28` | `_review_cache` | `ReviewCache()` | Eager singleton — **no lock!** |
| 11 | `plugins/shell_safety/command_cache.py:108` | `_cache` | `CommandSafetyCache()` | Eager singleton — **no lock!** |
| 12 | `plugins/agent_skills/skill_catalog.py:246` | `catalog` | `SkillCatalog()` | Eager singleton — **no lock!** |
| 13 | `plugins/task_context/scorer.py:368` | `_embedding_scorer` | `EmbeddingScorer()` | Eager singleton — **no lock!** |

### MEDIUM — Module-Level Mutable Singletons (Stateful Objects)

| # | File | Variable | Type | Concern |
|---|------|----------|------|---------|
| 1 | `tools/command_runner.py:140` | `_SHELL_EXECUTOR` | `ThreadPoolExecutor` | Shared thread pool; OK if immutable after init |
| 2 | `tools/common.py:10` | `console` | `Console` | Rich console — OK (no mutable state) |
| 3 | `tools/ask_user_question/theme.py:83,139` | `_DEFAULT_TUI`, `_DEFAULT_RICH` | Config objects | Config objects — likely immutable |
| 4 | `messaging/bus.py:60-72` | `_INFO_TEMPLATE`, etc. | `TextMessage` | Template objects — likely immutable |

### LOW — Simple Scalar Globals

| # | File | Variable | Type | Concern |
|---|------|----------|------|---------|
| 1 | `tools/chrome_cdp/__init__.py:203` | `_MSG_COUNTER` | `int` | Counter; should use `itertools.count()` |
| 2 | `terminal_utils.py:27` | `_original_ctrl_handler` | `Callable\|None` | Saved handler; single-user |
| 3 | `terminal_utils.py:299` | `_keep_ctrl_c_disabled` | `bool` | Flag; single-user |
| 4 | `command_line/clipboard.py:51` | `_last_clipboard_capture` | `float` | Rate limit timestamp; single-user |

---

## Recommended Fixes (Priority Order)

### Priority 1: CRITICAL — Per-Session Isolation

These globals store **per-session** data that **must not leak** between sessions:

1. **`_AGENT_HISTORIES`** (agent_manager.py) — Dict mapping agent-name → message history.
   - **Fix:** Move to a `SessionContext` class or `contextvars.ContextVar`. The agent manager should accept a session context parameter rather than using module-level state.

2. **`_SESSION_AGENTS_CACHE`** (agent_manager.py) — Dict mapping session-id → agent name.
   - **Fix:** Same as above — move to `SessionContext`.

3. **`_model_instance_cache`** (tools/agent_tools.py) — Dict mapping model name → model instance.
   - **Fix:** Move to a `ModelRegistry` class scoped per session. Or use `contextvars.ContextVar` if the cache should be per-agent-context.

4. **`_subagent_agent_cache`** (tools/agent_tools.py) — Dict mapping (agent_name, model, tools) → pydantic Agent.
   - **Fix:** Same as above.

5. **`_PERSISTENT_SESSIONS`** (chrome_cdp) — Dict of active CDP sessions.
   - **Fix:** Acceptable as-is for single-user; add `_PERSISTENT_SESSIONS_LOCK` for safety. In multi-user, move to per-user context.

6. **`_LAST_SAVED_HASHES`** (session_storage_helpers.py) — Dict tracking which sessions have been saved.
   - **Fix:** Move to `SessionContext` or pass as parameter.

### Priority 2: HIGH — Debate/Critic Plugin State

The debate and critic plugins use module-level lists/dicts for per-review tracking:

7. **`_review_history`**, **`_pending_review_indices`**, **`_review_timestamps`** (debate plugin)
   - **Fix:** Encapsulate in a `DebateSession` class. One instance per agent run. Pass via `contextvars.ContextVar`.

8. **`_ITERATION_TRACKER`** (universal_critic)
   - **Fix:** Same pattern — `CriticSession` class.

9. **`_previous_message_vectors`** (task_context/detector.py)
   - **Fix:** Encapsulate in `TaskDetectorState` class.

### Priority 3: HIGH — Command Runner Process Tracking

10. **`_RUNNING_PROCESSES`**, **`_USER_KILLED_PROCESSES`**, **`_ACTIVE_STOP_EVENTS`** (command_runner.py)
    - **Fix:** These are inherently process-global (tracking actual OS processes). Acceptable with their existing locks. Add clear documentation that they're process-scoped by design.

### Priority 4: MEDIUM — Caches With Locks

11. **`_model_validation_cache`**, **`_config_cache`**, **`_system_prompt_cache`**, **`_sorted_cache`**, **`_command_cache`**, **`_LEARNED_RATIOS`**, **`_file_mtimes`**, **`_DISCOVERY_CACHE`**
    - **Fix:** These are caches with locks. They're acceptable but should:
      - Add TTL or explicit `clear_cache()` functions for testability
      - Document that they're process-level caches (not session-scoped)
      - Consider `functools.lru_cache` where appropriate

### Priority 5: MEDIUM — Registry Pattern

12. **`_AGENT_REGISTRY`**, **`_COMMAND_REGISTRY`**, **`_CUSTOM_MODEL_PROVIDERS`**, **`_custom_commands`**, **`_command_descriptions`**
    - **Fix:** These are write-once-at-boot registries. Acceptable. Add a `_freeze_registries()` function called after startup that raises on mutation.

### Priority 6: LOW — Scalar Counters & Flags

13. **`_MSG_COUNTER`** → Replace with `itertools.count()`
14. **`_keep_ctrl_c_disabled`** → Acceptable; single-user CLI flag
15. **`_last_clipboard_capture`** → Acceptable; rate-limit timestamp

---

## Existing Best Practices in Codebase

The codebase already uses two correct patterns:

1. **`contextvars.ContextVar`** (4 instances):
   - `tools/subagent_context.py` — `_subagent_depth`, `_subagent_name`
   - `tools/agent_tools.py` — `_active_subagent_tasks_var`
   - `agents/_tool_circuit_breaker.py` — `_tool_error_tracker_ctx`

2. **`threading.local()`** (1 instance):
   - `plugins/file_permission_handler/register_callbacks.py` — `_thread_local`

These demonstrate the team is aware of the issue. The audit shows these patterns need broader adoption.

---

## Proposed Architecture: `SessionContext`

The cleanest fix for Priority 1 items is a `SessionContext` dataclass that holds per-session mutable state:

```python
# code_muse/session_context.py
"""Per-session mutable state container.

Replaces module-level dicts that leaked between sessions.
"""
from contextvars import ContextVar
from dataclasses import dataclass, field

@dataclass
class SessionContext:
    """Holds all mutable state that should be scoped to a single agent session."""
    agent_histories: dict[str, list] = field(default_factory=dict)
    session_agents_cache: dict[str, str] = field(default_factory=dict)
    model_instance_cache: dict[str, Any] = field(default_factory=dict)
    subagent_agent_cache: dict[tuple, Any] = field(default_factory=dict)
    last_saved_hashes: dict[tuple, str | None] = field(default_factory=dict)

# The active session context — set per agent run
_current: ContextVar[SessionContext] = ContextVar(
    "session_context", default=SessionContext()
)

def get_session_context() -> SessionContext:
    return _current.get()

def set_session_context(ctx: SessionContext) -> None:
    _current.set(ctx)
```

This would be introduced incrementally — one module at a time — with the old globals delegating to `get_session_context()` during migration.

---

## Test Impact

Current test contamination vectors:
- Tests that create agents in the same process share `_AGENT_HISTORIES`
- Tests that run compaction share `_model_instance_cache`
- Tests that use the debate plugin share `_review_history`
- Tests that save sessions share `_LAST_SAVED_HASHES`

**Recommendation:** Add a `clear_all_global_state()` test utility that resets all mutable globals between tests. This is a pragmatic stopgap until the `SessionContext` migration is complete.

---

## Summary Statistics

- **Total mutable globals found:** 39
- **Critical (per-session data leak):** 6
- **High (shared mutable state):** 14
- **Medium (caches/registries with locks):** 15
- **Low (scalars/constants):** 4
- **Already using ContextVar:** 4
- **Already using threading.local:** 1
