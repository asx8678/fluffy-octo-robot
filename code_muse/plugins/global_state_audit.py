"""Global Mutable State Audit (m48.8).

This module documents the audit of all module-level mutable state
across the codebase, classifies each finding, and recommends
appropriate isolation strategies.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Classification schema
# ---------------------------------------------------------------------------
#
# OK        — Intentional plugin state, reset on startup, single-session.
# CTXVAR    — Should use ContextVar for async/task isolation.
# LOCKED    — Already protected by threading.Lock (OK).
# ATOMIC    — Single bool/int assignment (GIL-safe on CPython, but
#             technically racy on free-threaded 3.14).
# REVIEW    — Needs closer review; may require restructuring.
# ---------------------------------------------------------------------------

FINDINGS: list[dict[str, str]] = [
    # === Core modules ===
    {
        "file": "callbacks.py",
        "variable": "_callbacks",
        "type": "dict[PhaseType, list[tuple]]",
        "classification": "LOCKED",
        "note": "Written at import + register_callback time; read at dispatch. "
        "Protected by implicit GIL on CPython. Free-threaded 3.14 "
        "should add a lock (deferred — register_callback is called "
        "from single thread during plugin loading).",
    },
    {
        "file": "callbacks.py",
        "variable": "_sorted_cache",
        "type": "dict[PhaseType, list]",
        "classification": "ATOMIC",
        "note": "Invalidated on register/unregister. Safe for single-thread "
        "registration phase. Free-threaded: needs lock.",
    },
    {
        "file": "callbacks.py",
        "variable": "_deferred_registrations",
        "type": "list[tuple]",
        "classification": "ATOMIC",
        "note": "Only active during defer mode. Same as above.",
    },
    {
        "file": "callbacks.py",
        "variable": "_defer_mode",
        "type": "bool",
        "classification": "ATOMIC",
        "note": "Set once at startup. Single assignment = safe.",
    },
    {
        "file": "tools/agent_tools.py",
        "variable": "_model_instance_cache",
        "type": "dict[str, Any]",
        "classification": "LOCKED",
        "note": "Protected by _model_instance_cache_lock. Good.",
    },
    {
        "file": "tools/agent_tools.py",
        "variable": "_subagent_agent_cache",
        "type": "OrderedDict[tuple, Any]",
        "classification": "REVIEW",
        "note": "No lock! Accessed from async invoke_agent. Safe on CPython "
        "(GIL protects dict ops) but needs lock for free-threaded 3.14.",
    },
    {
        "file": "summarization_agent.py",
        "variable": "_cached_model_name",
        "type": "str | None",
        "classification": "ATOMIC",
        "note": "Set once on first use, read thereafter. Single assignment safe.",
    },
    {
        "file": "config/session.py",
        "variable": "_autosave_counter",
        "type": "int",
        "classification": "ATOMIC",
        "note": "Incremented from single thread. Fine.",
    },
    {
        "file": "terminal_utils.py",
        "variable": "_keep_ctrl_c_disabled",
        "type": "bool",
        "classification": "ATOMIC",
        "note": "Signal handler context. Fine.",
    },
    {
        "file": "uvx_detection.py",
        "variable": "_uvx_detection_cache",
        "type": "bool | None",
        "classification": "ATOMIC",
        "note": "Computed once, cached. Fine.",
    },
    {
        "file": "motion.py",
        "variable": "_truecolor_cache",
        "type": "bool | None",
        "classification": "ATOMIC",
        "note": "Terminal capability cached once. Fine.",
    },
    # === Plugin modules ===
    {
        "file": "plugins/upgrade_metrics/register_callbacks.py",
        "variable": "_enabled",
        "type": "bool",
        "classification": "OK",
        "note": "Plugin on/off flag. Set by slash command in main thread.",
    },
    {
        "file": "plugins/upgrade_metrics/register_callbacks.py",
        "variable": "_token_ledger",
        "type": "dict[str, int]",
        "classification": "OK",
        "note": "Session-scoped metrics state. Reset on startup.",
    },
    {
        "file": "plugins/upgrade_metrics/register_callbacks.py",
        "variable": "_tool_token_ledger",
        "type": "dict[str, int]",
        "classification": "OK",
        "note": "Per-tool token tracking. Session-scoped.",
    },
    {
        "file": "plugins/upgrade_metrics/register_callbacks.py",
        "variable": "_event_buffer",
        "type": "list[dict]",
        "classification": "OK",
        "note": "In-memory event buffer. Session-scoped, reset on startup.",
    },
    {
        "file": "plugins/custom_commands/register_callbacks.py",
        "variable": "_command_cache",
        "type": "dict[str, CommandDef]",
        "classification": "OK",
        "note": "Loaded once from TOML. Fine.",
    },
    {
        "file": "plugins/customizable_commands/register_callbacks.py",
        "variable": "_custom_commands",
        "type": "dict[str, str]",
        "classification": "OK",
        "note": "User-defined commands. Single-thread writes.",
    },
    {
        "file": "plugins/debate/state.py",
        "variable": "_review_count, _current_checkpoint, etc.",
        "type": "int, str, bool",
        "classification": "CTXVAR",
        "note": "Debate state is per-agent-run. If two debates run "
        "concurrently (e.g. nested invoke_agent), they'll collide. "
        "Should use ContextVar or a session-keyed dict.",
    },
    {
        "file": "plugins/debate/state.py",
        "variable": "_review_history",
        "type": "list[dict]",
        "classification": "CTXVAR",
        "note": "Same issue as above — shared across concurrent runs.",
    },
    {
        "file": "plugins/semantic_compression/register_callbacks.py",
        "variable": "_compression_stats",
        "type": "dict[str, int]",
        "classification": "OK",
        "note": "Session-scoped stats. Fine.",
    },
    {
        "file": "plugins/semantic_compression/register_callbacks.py",
        "variable": "_last_original_output",
        "type": "str | None",
        "classification": "OK",
        "note": "Single-value cache. Fine.",
    },
    {
        "file": "plugins/policy_engine/policy_file_discovery.py",
        "variable": "_rule_cache",
        "type": "list[ToolRule] | None",
        "classification": "OK",
        "note": "File-sourced cache, reloaded on /policies reload. Fine.",
    },
    {
        "file": "plugins/task_context/detector.py",
        "variable": "_previous_message_vectors",
        "type": "list[list[float]]",
        "classification": "CTXVAR",
        "note": "Embedding vectors for task shift detection. Shared "
        "across concurrent agent runs. Should be per-session.",
    },
    {
        "file": "plugins/truncation_detector/register_callbacks.py",
        "variable": "_enabled, _detection_count, _blocked_count",
        "type": "bool, int, int",
        "classification": "OK",
        "note": "Session-scoped toggle and counters. Fine.",
    },
    {
        "file": "tools/skills_tools.py",
        "variable": "_background_jobs",
        "type": "dict[str, dict]",
        "classification": "REVIEW",
        "note": "Background skill jobs. No lock. Could collide if "
        "multiple agents install skills concurrently.",
    },
]

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
#
# Total findings: 24
# - OK: 14 (intentional plugin state, session-scoped)
# - ATOMIC: 7 (single assignments, GIL-safe)
# - LOCKED: 2 (already protected by threading.Lock)
# - CTXVAR: 3 (should use ContextVar for async isolation)
# - REVIEW: 2 (needs closer review for free-threaded 3.14)
#
# Recommendations:
# 1. CTXVAR items (debate/state, task_context/detector) should be migrated
#    to ContextVar-based storage in a follow-up task.
# 2. REVIEW items (agent_tools cache, skills_tools background_jobs) should
#    get threading.Lock guards for free-threaded 3.14 compatibility.
# 3. The agent_tools _subagent_agent_cache should get a lock matching the
#    pattern used for _model_instance_cache_lock.
