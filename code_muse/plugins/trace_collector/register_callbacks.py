"""Callback registration for the Trace Collector plugin.

Registers hooks for:
- ``agent_run_start``: Create a new trace context and record span start.
- ``agent_run_end``: Record span end with token delta and success/error.
- ``agent_exception``: Record span failure with diagnostics.
- ``stream_event``: Enrich stream events with trace/span fields.
- ``post_tool_call``: Record tool calls with duration and token delta.
- ``custom_command``: ``/trace`` commands for querying traces.

All events are written to NDJSON under ``~/.muse/traces/`` and can
be correlated with ``upgrade_metrics`` events via shared trace_id.
"""

from __future__ import annotations

import logging
from typing import Any

from code_muse.callbacks import register_callback
from code_muse.messaging import emit_info, emit_warning
from code_muse.plugins.trace_collector import (
    TraceContext,
    clear_current_trace_context,
    get_current_trace_context,
    set_current_trace_context,
)
from code_muse.plugins.trace_collector.store import build_tree, load_trace, write_span

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Agent lifecycle hooks
# ---------------------------------------------------------------------------


async def _on_agent_run_start(
    agent_name: str,
    model_name: str,
    session_id: str | None = None,
) -> None:
    """Create or propagate a trace context when an agent run begins."""
    parent_ctx = get_current_trace_context()

    if parent_ctx is None:
        # Top-level run: create a new trace
        ctx = TraceContext(agent_name=agent_name)
    else:
        # Sub-agent run: create a child span
        ctx = parent_ctx.child(agent_name)

    set_current_trace_context(ctx)

    write_span(
        trace_id=ctx.trace_id,
        span_id=ctx.current_span_id,
        parent_span_id=ctx.parent_span_id,
        agent_name=agent_name,
        event_type="span_start",
        data={
            "model": model_name,
            "session_id": session_id,
        },
        turn=ctx.turn,
        swarm_id=ctx.swarm_id,
    )

    # Emit to upgrade_metrics for correlation
    try:
        from code_muse.plugins.upgrade_metrics import emit_metric

        emit_metric(
            "trace_span_start",
            {
                "trace_id": ctx.trace_id,
                "span_id": ctx.current_span_id,
                "agent": agent_name,
                "model": model_name,
            },
        )
    except ImportError:
        pass


async def _on_agent_run_end(
    agent_name: str,
    model_name: str,
    session_id: str | None = None,
    success: bool = True,
    error: str | None = None,
    response_text: str | None = None,
    metadata: dict | None = None,
) -> None:
    """Record span end when an agent run completes."""
    ctx = get_current_trace_context()
    if ctx is None:
        return

    # Token delta estimation
    tokens = 0
    if response_text:
        tokens = max(1, len(response_text) // 4)
    if metadata and isinstance(metadata, dict):
        usage = metadata.get("usage")
        if isinstance(usage, dict):
            tokens = usage.get("total_tokens", tokens)

    write_span(
        trace_id=ctx.trace_id,
        span_id=ctx.current_span_id,
        parent_span_id=ctx.parent_span_id,
        agent_name=agent_name,
        event_type="span_end",
        data={
            "model": model_name,
            "session_id": session_id,
            "success": success,
            "tokens": tokens,
            "error": error[:200] if error else None,
        },
        turn=ctx.turn,
        swarm_id=ctx.swarm_id,
    )

    # If this is a sub-agent, restore parent context
    if ctx.parent_span_id is not None:
        # Reconstruct parent context (simplified — we don't store full
        # parent state, just move up one level)
        parent_ctx = TraceContext(
            trace_id=ctx.trace_id,
            current_span_id=ctx.parent_span_id,
            agent_name="muse",  # Best guess
            swarm_id=ctx.swarm_id,
        )
        set_current_trace_context(parent_ctx)
    else:
        # Root agent finished — clear the trace context
        clear_current_trace_context()


async def _on_agent_exception(
    exception: BaseException,
    *args: Any,
    **kwargs: Any,
) -> None:
    """Record a span failure when an unhandled agent error occurs."""
    ctx = get_current_trace_context()
    if ctx is None:
        return

    write_span(
        trace_id=ctx.trace_id,
        span_id=ctx.current_span_id,
        parent_span_id=ctx.parent_span_id,
        agent_name=ctx.agent_name,
        event_type="span_error",
        data={
            "exception_type": type(exception).__name__,
            "exception_message": str(exception)[:500],
        },
        turn=ctx.turn,
        swarm_id=ctx.swarm_id,
    )


# ---------------------------------------------------------------------------
# Stream event enrichment
# ---------------------------------------------------------------------------


def _on_stream_event(
    event_type: str,
    event_data: dict[str, Any],
    agent_session_id: str | None = None,
) -> None:
    """Enrich stream events with trace context fields.

    This adds ``trace_id`` and ``span_id`` to stream event payloads
    so that consumers can correlate events with the invocation tree.
    """
    ctx = get_current_trace_context()
    if ctx is None:
        return

    event_data.setdefault("trace_id", ctx.trace_id)
    event_data.setdefault("span_id", ctx.current_span_id)


# ---------------------------------------------------------------------------
# Post-tool-call recording
# ---------------------------------------------------------------------------


async def _on_post_tool_call(
    tool_name: str,
    tool_args: dict,
    result: Any,
    duration_ms: float,
    context: Any = None,
) -> Any:
    """Record tool calls within a span for full trace visibility."""
    ctx = get_current_trace_context()
    if ctx is None:
        return None

    write_span(
        trace_id=ctx.trace_id,
        span_id=ctx.current_span_id,
        parent_span_id=ctx.parent_span_id,
        agent_name=ctx.agent_name,
        event_type="tool_call",
        data={
            "tool": tool_name,
            "duration_ms": round(duration_ms, 2),
        },
        turn=ctx.turn,
        swarm_id=ctx.swarm_id,
    )

    return None


# ---------------------------------------------------------------------------
# /trace slash commands
# ---------------------------------------------------------------------------


def _on_custom_command(command: str, name: str) -> bool | str | None:
    """Handle ``/trace`` commands for trace inspection."""
    if name != "trace":
        return None

    parts = command.split(maxsplit=2)
    sub = parts[1].strip().lower() if len(parts) > 1 else "help"

    if sub == "show":
        if len(parts) < 3:
            # Show current trace if active
            ctx = get_current_trace_context()
            if ctx:
                emit_info(
                    f"🔍 Current trace: trace_id={ctx.trace_id}\n"
                    f"   span_id={ctx.current_span_id}\n"
                    f"   parent={ctx.parent_span_id}\n"
                    f"   agent={ctx.agent_name}\n"
                    f"   turn={ctx.turn}"
                )
            else:
                emit_info("No active trace. Usage: /trace show <trace_id>")
            return True

        trace_id = parts[2].strip()
        spans = load_trace(trace_id)
        if not spans:
            emit_warning(f"No spans found for trace_id={trace_id[:16]}")
            return True

        lines = [f"🔍 Trace: {trace_id[:16]}  ({len(spans)} span(s))"]
        for span in spans:
            event = span.get("event_type", "unknown")
            agent = span.get("agent_name", "?")
            span_id = span.get("span_id", "?")
            parent = span.get("parent_span_id")
            indent = "  " if parent else ""
            parent_str = f"← {parent}" if parent else "(root)"
            lines.append(f"  {indent}{event}: {agent} [{span_id}] {parent_str}")
            if "tool" in span:
                lines.append(f"  {indent}  tool: {span['tool']}")
            if "success" in span:
                status = "✓" if span["success"] else "✗"
                lines.append(f"  {indent}  {status} tokens={span.get('tokens', '?')}")

        emit_info("\n".join(lines))
        return True

    if sub == "tree":
        if len(parts) < 3:
            emit_info("Usage: /trace tree <trace_id>")
            return True

        trace_id = parts[2].strip()
        spans = load_trace(trace_id)
        if not spans:
            emit_warning(f"No spans found for trace_id={trace_id[:16]}")
            return True

        tree = build_tree(spans)
        lines = [
            f"🔍 Trace tree: {tree.get('trace_id', '?')[:16]}  "
            f"({tree['total_spans']} spans)"
        ]

        def _render_node(node: dict, depth: int = 0) -> None:
            prefix = "  " * (depth + 1)
            event = node.get("event_type", "?")
            agent = node.get("agent_name", "?")
            span_id = node.get("span_id", "?")
            lines.append(f"{prefix}├─ {event}: {agent} [{span_id}]")
            for child in node.get("children", []):
                _render_node(child, depth + 1)

        for root in tree.get("roots", []):
            _render_node(root)

        emit_info("\n".join(lines))
        return True

    if sub == "current":
        ctx = get_current_trace_context()
        if ctx:
            emit_info(
                f"🔍 Active trace context:\n"
                f"   trace_id:    {ctx.trace_id}\n"
                f"   span_id:     {ctx.current_span_id}\n"
                f"   parent:      {ctx.parent_span_id or '(root)'}\n"
                f"   agent:       {ctx.agent_name}\n"
                f"   turn:        {ctx.turn}\n"
                f"   swarm_id:    {ctx.swarm_id or 'n/a'}"
            )
        else:
            emit_info("No active trace context")
        return True

    if sub == "help":
        lines = [
            "🔍 Trace Collector Commands:",
            "   /trace current        — Show active trace context",
            "   /trace show [id]      — Show trace spans (current if no id)",
            "   /trace tree <id>      — Show trace as parent→child tree",
            "   /trace help           — Show this help",
        ]
        emit_info("\n".join(lines))
        return True

    emit_info("Usage: /trace current|show|tree|help")
    return True


def _on_custom_command_help() -> list[tuple[str, str]]:
    return [
        ("trace current", "Show active trace context"),
        ("trace show", "Show trace spans"),
        ("trace tree", "Show trace as parent→child tree"),
        ("trace help", "Show trace command help"),
    ]


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------


def _on_startup() -> None:
    """Clear any stale trace context on app boot."""
    clear_current_trace_context()
    logger.debug("Trace collector plugin initialised")


# ---------------------------------------------------------------------------
# Register all callbacks
# ---------------------------------------------------------------------------

register_callback("startup", _on_startup)
register_callback("agent_run_start", _on_agent_run_start)
register_callback("agent_run_end", _on_agent_run_end)
register_callback("agent_exception", _on_agent_exception)
register_callback("stream_event", _on_stream_event)
register_callback("post_tool_call", _on_post_tool_call)
register_callback("custom_command", _on_custom_command)
register_callback("custom_command_help", _on_custom_command_help)
