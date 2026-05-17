"""Callback registration for the Upgrade Metrics plugin.

Registers hooks for session-level token tracking, event recording with
JSONL persistence, and ``/metrics`` slash commands.

Token Ledger
------------
Maintains cumulative token counts at each pipeline stage:
``input``, ``after_compression``, ``after_compaction``, ``after_review``,
``current``.  :func:`record_tokens` adds to the existing value (cumulative).

Event System
------------
Core events: ``compression_applied``, ``context_pruned``,
``review_verdict``, ``task_archived``.  Each event is stored with
``{timestamp, event, data}`` in an in-memory buffer (capped at 500)
and appended to a JSONL log file.

JSONL Storage
-------------
Path: ``~/.muse/metrics/events.jsonl`` (directory created on first write).
Rotation: when file exceeds 5 MB, rename to ``events.jsonl.1`` (overwriting
old ``.1``) and start a fresh file.

Slash Commands
--------------
- ``/metrics compression`` — token savings from compression events
- ``/metrics context`` — pruning/compaction stats
- ``/metrics quality`` — review verdict distribution, override rate
- ``/metrics tools`` — per-tool token usage breakdown
- ``/metrics status`` — plugin status, events collected, ledger snapshot
- ``/metrics off`` — disable all metric hooks (hooks become no-ops)
- ``/metrics on`` — re-enable metric hooks
- ``/metrics reset`` — reset in-memory state (not JSONL file)
- ``/metrics help`` — show available commands

Both ``/metrics off`` and ``/upgrade-metrics off`` are accepted.
"""

import json
import logging
import time
from pathlib import Path
from typing import Any

from code_muse.callbacks import register_callback
from code_muse.config import paths as muse_paths
from code_muse.messaging import emit_info, emit_success, emit_warning

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_LEDGER_STAGES = (
    "input",
    "after_compression",
    "after_compaction",
    "after_review",
    "current",
)
_CORE_EVENTS = (
    "compression_applied",
    "context_pruned",
    "review_verdict",
    "task_archived",
)
_MAX_BUFFER_SIZE = 500
_ROTATION_SIZE_BYTES = 5 * 1024 * 1024  # 5 MB

# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------

_enabled: bool = True
_token_ledger: dict[str, int] = {stage: 0 for stage in _LEDGER_STAGES}
_event_buffer: list[dict[str, Any]] = []

# Per-tool-call token tracking: tool_name → cumulative token count.
# This enables ``/metrics tools`` to show which tools consume the most tokens.
_tool_token_ledger: dict[str, int] = {}


# ---------------------------------------------------------------------------
# JSONL helpers
# ---------------------------------------------------------------------------


def _metrics_dir() -> Path:
    """Return the directory for metrics JSONL files."""
    state_dir = getattr(muse_paths, "STATE_DIR", None)
    if state_dir is not None:
        return Path(state_dir) / "metrics"
    return Path.home() / ".muse" / "metrics"


def _jsonl_path() -> Path:
    """Return the path to the active events JSONL file."""
    return _metrics_dir() / "events.jsonl"


def _rotate_jsonl() -> None:
    """Rotate the JSONL file if it exceeds the size limit.

    Renames ``events.jsonl`` → ``events.jsonl.1`` (overwriting old ``.1``)
    and starts a fresh file.
    """
    try:
        path = _jsonl_path()
        if not path.exists():
            return
        if path.stat().st_size >= _ROTATION_SIZE_BYTES:
            rotated = path.with_suffix(".jsonl.1")
            path.rename(rotated)
            logger.info("Rotated metrics JSONL: %s → %s", path, rotated)
    except OSError:
        logger.debug("Could not rotate metrics JSONL file")


def _append_jsonl(entry: dict[str, Any]) -> None:
    """Append a single JSON line to the events JSONL file.

    Creates the directory and file if needed.  All I/O is wrapped in
    try/except — never crashes the app.
    """
    try:
        _rotate_jsonl()
        path = _jsonl_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, default=str) + "\n")
    except OSError:
        logger.debug("Could not write metrics JSONL entry")


# ---------------------------------------------------------------------------
# Token ledger
# ---------------------------------------------------------------------------


def record_tokens(stage: str, count: int) -> None:
    """Add *count* tokens to the ledger at the given *stage*.

    The value is cumulative — each call adds to the existing total.

    Args:
        stage: One of ``input``, ``after_compression``,
            ``after_compaction``, ``after_review``, ``current``.
        count: Number of tokens to add.

    Unknown stages are logged and ignored (never crashes the app).
    """
    if stage not in _token_ledger:
        logger.warning("Unknown ledger stage %r — ignoring %d tokens", stage, count)
        return
    _token_ledger[stage] += count


def get_ledger() -> dict[str, int]:
    """Return a snapshot of the token ledger.

    Returns:
        A dict mapping each stage name to its cumulative token count.
    """
    return dict(_token_ledger)


def _reset_ledger() -> None:
    """Zero out all token ledger stages."""
    for stage in _LEDGER_STAGES:
        _token_ledger[stage] = 0
    _tool_token_ledger.clear()


# ---------------------------------------------------------------------------
# Event recording
# ---------------------------------------------------------------------------


def emit_metric(event_name: str, data: dict[str, Any] | None = None) -> None:
    """Record a metric event into both the in-memory buffer and JSONL file.

    This is the **public integration point** other plugins call.  Import it
    from ``code_muse.plugins.upgrade_metrics``::

        from code_muse.plugins.upgrade_metrics import emit_metric
        emit_metric(
            "compression_applied",
            {
                "original_tokens": 5000,
                "compressed_tokens": 3000,
                "strategy": "semantic",
            },
        )

    When the plugin is disabled (via ``/metrics off``), this function
    returns silently — safe to call regardless of plugin state.

    If *data* contains both ``original_tokens`` and ``compressed_tokens``,
    ``tokens_saved`` is automatically computed and added to *data*.
    """
    global _event_buffer

    if not _enabled:
        return

    if not event_name or not isinstance(event_name, str):
        logger.debug("emit_metric called with invalid event_name: %r", event_name)
        return

    data = dict(data) if data else {}

    # Auto-compute token savings when both original and compressed counts given
    if "original_tokens" in data and "compressed_tokens" in data:
        data.setdefault(
            "tokens_saved",
            max(0, data["original_tokens"] - data["compressed_tokens"]),
        )

    entry: dict[str, Any] = {
        "timestamp": time.time(),
        "event": event_name,
        "data": data,
    }

    # In-memory buffer (capped at 500, oldest dropped)
    _event_buffer.append(entry)
    if len(_event_buffer) > _MAX_BUFFER_SIZE:
        _event_buffer.pop(0)

    # Persist to JSONL
    _append_jsonl(entry)


def _reset_events() -> None:
    """Clear the in-memory event buffer."""
    _event_buffer.clear()


def _reset_all() -> None:
    """Reset all in-memory state (ledger + events)."""
    _reset_ledger()
    _reset_events()


# ---------------------------------------------------------------------------
# Per-tool-call token tracking
# ---------------------------------------------------------------------------


def _extract_token_count(result: Any) -> int:
    """Best-effort extraction of token usage from a tool call result.

    Tool results vary in shape — some carry ``usage`` dicts from the
    model, others are plain strings.  We try common shapes and fall
    back to a character-based estimate.
    """
    if result is None:
        return 0

    # If the result is a dict with usage info
    if isinstance(result, dict):
        usage = result.get("usage") or result.get("_usage")
        if isinstance(usage, dict):
            return usage.get("total_tokens", 0) or usage.get("request_tokens", 0)
        # Some results have a ``response`` sub-dict with usage
        resp = result.get("response")
        if isinstance(resp, dict):
            usage = resp.get("usage")
            if isinstance(usage, dict):
                return usage.get("total_tokens", 0)

    # Character-based heuristic: ~4 chars per token
    try:
        text = str(result)
        return max(1, len(text) // 4)
    except Exception:
        return 0


def get_tool_token_ledger() -> dict[str, int]:
    """Return a snapshot of the per-tool-call token ledger."""
    return dict(_tool_token_ledger)


async def _on_post_tool_call(
    tool_name: str,
    tool_args: dict,
    result: Any,
    duration_ms: float,
    context: Any = None,
) -> Any:
    """Record per-tool-call token usage after every tool execution.

    Extracts token counts from the result (best-effort) and adds them
    to the per-tool ledger.  Also emits a ``tool_call`` metric event.
    """
    if not _enabled:
        return None

    try:
        token_count = _extract_token_count(result)
        _tool_token_ledger[tool_name] = (
            _tool_token_ledger.get(tool_name, 0) + token_count
        )

        # Also add to the cumulative input ledger
        record_tokens("input", token_count)

        # Emit tool_call event for full audit trail
        emit_metric(
            "tool_call",
            {
                "tool": tool_name,
                "tokens": token_count,
                "duration_ms": round(duration_ms, 2),
            },
        )
    except Exception:
        logger.debug("Failed to record tool metrics for %s", tool_name, exc_info=True)

    return None


async def _on_agent_run_end(
    agent_name: str,
    model_name: str,
    session_id: str | None = None,
    success: bool = True,
    error: str | None = None,
    response_text: str | None = None,
    metadata: dict | None = None,
) -> None:
    """Record token usage and outcome at the end of an agent run.

    Captures the total token cost of a sub-agent invocation, including
    success/failure status.  Feeds into the ``current`` ledger stage and
    emits an ``agent_run`` metric event.
    """
    if not _enabled:
        return

    try:
        # Estimate tokens from response text (character heuristic)
        tokens = 0
        if response_text:
            tokens = max(1, len(response_text) // 4)

        # Check metadata for actual usage (model-provided)
        if metadata and isinstance(metadata, dict):
            usage = metadata.get("usage")
            if isinstance(usage, dict):
                tokens = usage.get("total_tokens", tokens)

        record_tokens("current", tokens)

        emit_metric(
            "agent_run",
            {
                "agent": agent_name,
                "model": model_name,
                "session_id": session_id,
                "success": success,
                "tokens": tokens,
                "error": error[:200] if error else None,
            },
        )
    except Exception:
        logger.debug(
            "Failed to record agent_run_end metrics for %s",
            agent_name,
            exc_info=True,
        )


# ---------------------------------------------------------------------------
# Computed stats (for slash commands)
# ---------------------------------------------------------------------------


def _compression_stats() -> dict[str, Any]:
    """Compute compression token savings from buffered events."""
    total_original = 0
    total_compressed = 0
    strategy_counts: dict[str, int] = {}
    strategy_saved: dict[str, int] = {}

    for entry in _event_buffer:
        if entry.get("event") != "compression_applied":
            continue
        d = entry.get("data", {})
        orig = d.get("original_tokens", 0)
        comp = d.get("compressed_tokens", 0)
        total_original += orig
        total_compressed += comp
        strategy = d.get("strategy", "unknown")
        strategy_counts[strategy] = strategy_counts.get(strategy, 0) + 1
        strategy_saved[strategy] = strategy_saved.get(strategy, 0) + (orig - comp)

    total_saved = total_original - total_compressed
    pct = (total_saved / total_original * 100) if total_original else 0.0

    return {
        "total_original": total_original,
        "total_compressed": total_compressed,
        "total_saved": total_saved,
        "savings_pct": round(pct, 1),
        "strategy_counts": strategy_counts,
        "strategy_saved": strategy_saved,
    }


def _context_stats() -> dict[str, Any]:
    """Compute context pruning/compaction stats from buffered events."""
    messages_pruned = 0
    tokens_saved = 0
    compaction_count = 0

    for entry in _event_buffer:
        evt = entry.get("event")
        d = entry.get("data", {})
        if evt == "context_pruned":
            messages_pruned += d.get("messages_pruned", 0)
            tokens_saved += d.get("tokens_saved", 0)
        elif evt == "compression_applied" and d.get("strategy") == "compaction":
            compaction_count += 1
            tokens_saved += d.get("tokens_saved", 0)

    return {
        "messages_pruned": messages_pruned,
        "tokens_saved": tokens_saved,
        "compaction_count": compaction_count,
    }


def _quality_stats() -> dict[str, Any]:
    """Compute review verdict distribution and override rate."""
    verdict_counts: dict[str, int] = {}
    total = 0
    override_count = 0

    for entry in _event_buffer:
        if entry.get("event") != "review_verdict":
            continue
        d = entry.get("data", {})
        verdict = d.get("verdict", "unknown")
        verdict_counts[verdict] = verdict_counts.get(verdict, 0) + 1
        total += 1
        if d.get("overridden", False):
            override_count += 1

    override_rate = (override_count / total * 100) if total else 0.0

    return {
        "verdict_counts": verdict_counts,
        "total_reviews": total,
        "override_count": override_count,
        "override_rate": round(override_rate, 1),
    }


# ---------------------------------------------------------------------------
# Slash commands
# ---------------------------------------------------------------------------


def _on_custom_command(command: str, name: str) -> bool | None:
    """Handle ``/metrics`` and ``/upgrade-metrics`` slash commands.

    Subcommands:
        compression — Show token savings from compression events
        context     — Show context pruning/compaction stats
        quality     — Show review verdict distribution, override rate
        status      — Show plugin status, events collected, ledger snapshot
        off         — Disable all metric hooks (hooks become no-ops)
        on          — Re-enable metric hooks
        reset       — Reset in-memory state (not JSONL file)
        help        — Show available commands
    """
    global _enabled

    # Accept both /metrics and /upgrade-metrics
    if name not in ("metrics", "upgrade-metrics"):
        return None

    parts = command.split(maxsplit=1)
    sub = parts[1].strip().lower() if len(parts) > 1 else "status"

    # --- Disable ---
    if sub == "off":
        _enabled = False
        emit_warning("📊 Upgrade metrics disabled")
        return True

    # --- Enable ---
    if sub == "on":
        _enabled = True
        emit_success("📊 Upgrade metrics enabled")
        return True

    # --- Reset ---
    if sub == "reset":
        _reset_all()
        emit_success("📊 Upgrade metrics reset (in-memory state cleared)")
        return True

    # --- Compression stats ---
    if sub == "compression":
        stats = _compression_stats()
        lines = [
            "📊 Compression Metrics:",
            f"   Total original:  {stats['total_original']:,} tokens",
            f"   Total compressed: {stats['total_compressed']:,} tokens",
            f"   Total saved:     {stats['total_saved']:,} tokens "
            f"({stats['savings_pct']}%)",
        ]
        if stats["strategy_counts"]:
            lines.append("")
            lines.append("   Per-strategy breakdown:")
            for strategy in sorted(stats["strategy_counts"]):
                cnt = stats["strategy_counts"][strategy]
                saved = stats["strategy_saved"].get(strategy, 0)
                lines.append(
                    f"     {strategy}: {cnt} applications, {saved:,} tokens saved"
                )
        emit_info("\n".join(lines))
        return True

    # --- Context stats ---
    if sub == "context":
        stats = _context_stats()
        lines = [
            "📊 Context Metrics:",
            f"   Messages pruned:  {stats['messages_pruned']}",
            f"   Tokens saved:    {stats['tokens_saved']:,}",
            f"   Compaction runs: {stats['compaction_count']}",
        ]
        emit_info("\n".join(lines))
        return True

    # --- Quality stats ---
    if sub == "quality":
        stats = _quality_stats()
        lines = [
            "📊 Quality Metrics:",
            f"   Total reviews:    {stats['total_reviews']}",
        ]
        if stats["verdict_counts"]:
            lines.append("")
            lines.append("   Verdict distribution:")
            for verdict in sorted(stats["verdict_counts"]):
                cnt = stats["verdict_counts"][verdict]
                lines.append(f"     {verdict}: {cnt}")
        lines.append(
            f"   Overrides: {stats['override_count']} ({stats['override_rate']}%)"
        )
        emit_info("\n".join(lines))
        return True

    # --- Tool token usage ---
    if sub == "tools":
        tool_ledger = get_tool_token_ledger()
        lines = ["📊 Tool Token Usage:"]
        if not tool_ledger:
            lines.append("   (no tool calls recorded yet)")
        else:
            # Sort by token usage descending
            sorted_tools = sorted(tool_ledger.items(), key=lambda x: x[1], reverse=True)
            total = sum(tool_ledger.values())
            for tool_name, tokens in sorted_tools:
                pct = (tokens / total * 100) if total else 0
                lines.append(f"   {tool_name}: {tokens:,} tokens ({pct:.1f}%)")
            lines.append(f"   Total: {total:,} tokens")
        emit_info("\n".join(lines))
        return True

    # --- Status ---
    if sub == "status":
        ledger = get_ledger()
        state = "enabled" if _enabled else "disabled"
        lines = [
            f"📊 Upgrade Metrics Status: {state}",
            f"   Events collected: {len(_event_buffer)}",
            "",
            "   Token Ledger:",
        ]
        for stage in _LEDGER_STAGES:
            lines.append(f"     {stage}: {ledger[stage]:,}")
        emit_info("\n".join(lines))
        return True

    # --- Help ---
    if sub == "help":
        lines = [
            "📊 Upgrade Metrics Commands:",
            "   /metrics compression — Token savings from compression events",
            "   /metrics context     — Context pruning/compaction stats",
            "   /metrics quality     — Review verdict distribution, override rate",
            "   /metrics tools     — Per-tool token usage breakdown",
            "   /metrics off         — Disable all metric hooks",
            "   /metrics on          — Re-enable metric hooks",
            "   /metrics reset       — Reset in-memory state (not JSONL)",
            "   /metrics help        — Show this help",
        ]
        emit_info("\n".join(lines))
        return True

    # --- Unknown subcommand ---
    emit_info(
        "Usage: /metrics compression|context|quality|tools|status|off|on|reset|help"
    )
    return True


def _on_custom_command_help() -> list[tuple[str, str]]:
    """Return help entries for the ``/metrics`` command family."""
    return [
        ("metrics compression", "Token savings from compression events"),
        ("metrics context", "Context pruning/compaction stats"),
        ("metrics quality", "Review verdict distribution, override rate"),
        ("metrics tools", "Per-tool token usage breakdown"),
        ("metrics status", "Plugin status, events, ledger snapshot"),
        ("metrics off", "Disable all metric hooks"),
        ("metrics on", "Re-enable metric hooks"),
        ("metrics reset", "Reset in-memory state (not JSONL)"),
        ("metrics help", "Show available metrics commands"),
        ("upgrade-metrics off", "Disable all metric hooks (alias)"),
        ("upgrade-metrics on", "Re-enable metric hooks (alias)"),
    ]


# ---------------------------------------------------------------------------
# Startup / Shutdown hooks
# ---------------------------------------------------------------------------


def _on_startup() -> None:
    """Initialize in-memory state on app boot."""
    global _enabled
    _enabled = True
    _reset_all()
    logger.debug("Upgrade Metrics plugin initialised")


def _on_shutdown() -> None:
    """Log final stats at debug level on graceful exit."""
    logger.debug(
        "Upgrade Metrics shutdown — events: %d, ledger: %s",
        len(_event_buffer),
        get_ledger(),
    )


# ---------------------------------------------------------------------------
# Register all callbacks
# ---------------------------------------------------------------------------

register_callback("startup", _on_startup)
register_callback("shutdown", _on_shutdown)
register_callback("custom_command", _on_custom_command)
register_callback("custom_command_help", _on_custom_command_help)
register_callback("post_tool_call", _on_post_tool_call)
register_callback("agent_run_end", _on_agent_run_end)
