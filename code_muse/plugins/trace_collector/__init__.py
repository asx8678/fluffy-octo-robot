"""Trace context propagation for causal, tree-structured agent visibility.

Provides a lightweight ``TraceContext`` dataclass that flows through
the agent invocation tree, enabling debuggable multi-agent traces
with parent→child→grandchild span links.

This is the core module used by both the ``trace_collector`` plugin
and the ``invoke_agent`` path in ``agent_tools.py``.
"""

from __future__ import annotations

import uuid
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class TraceContext:
    """Immutable trace context propagated through agent invocation trees.

    Attributes:
        trace_id: Unique identifier for the entire trace (top-level run).
        parent_span_id: Span ID of the parent, or None for the root.
        current_span_id: Span ID of this span.
        turn: Sequential turn number within this span.
        agent_name: Name of the agent executing this span.
        swarm_id: Optional collaboration group ID.
    """

    trace_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    parent_span_id: str | None = None
    current_span_id: str = field(default_factory=lambda: str(uuid.uuid4())[:12])
    turn: int = 0
    agent_name: str = "muse"
    swarm_id: str | None = None

    def child(self, agent_name: str) -> TraceContext:
        """Create a child span context for a sub-agent invocation.

        The child's ``parent_span_id`` points to this span, and
        ``turn`` resets to 0.
        """
        return TraceContext(
            trace_id=self.trace_id,
            parent_span_id=self.current_span_id,
            current_span_id=str(uuid.uuid4())[:12],
            turn=0,
            agent_name=agent_name,
            swarm_id=self.swarm_id,
        )

    def next_turn(self) -> TraceContext:
        """Advance to the next turn within this span."""
        return TraceContext(
            trace_id=self.trace_id,
            parent_span_id=self.parent_span_id,
            current_span_id=self.current_span_id,
            turn=self.turn + 1,
            agent_name=self.agent_name,
            swarm_id=self.swarm_id,
        )

    def as_dict(self) -> dict[str, Any]:
        """Serialise to a dict for JSONL/event emission."""
        return {
            "trace_id": self.trace_id,
            "parent_span_id": self.parent_span_id,
            "current_span_id": self.current_span_id,
            "turn": self.turn,
            "agent_name": self.agent_name,
            "swarm_id": self.swarm_id,
        }


# ---------------------------------------------------------------------------
# ContextVar-based propagation
# ---------------------------------------------------------------------------

_current_trace: ContextVar[TraceContext | None] = ContextVar(
    "current_trace", default=None
)


def get_current_trace_context() -> TraceContext | None:
    """Return the active trace context, or None if no trace is active."""
    return _current_trace.get()


def set_current_trace_context(ctx: TraceContext) -> None:
    """Set the active trace context (used by invoke_agent)."""
    _current_trace.set(ctx)


def clear_current_trace_context() -> None:
    """Clear the trace context (used after agent run completes)."""
    _current_trace.set(None)
