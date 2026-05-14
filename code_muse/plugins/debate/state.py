"""Session state management for the Debate Mode plugin.

Tracks per-session counters for budget enforcement and loop detection,
plus an active/inactive flag for agent-run lifecycle tracking.

State is held in module-level variables — one session per Muse invocation.
All mutations go through :class:`DebateState` so counters stay consistent.
"""

import threading
from typing import Any

from code_muse.plugins.debate.config import (
    get_debate_max_loops,
    get_debate_max_reviews,
)
from code_muse.plugins.debate.schemas import VerdictKind

# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------

_review_count: int = 0
_current_checkpoint: int = 0
_consecutive_revisions: int = 0
_last_verdict: VerdictKind | None = None

# Review history: list of dicts with checkpoint, verdict, summary, latency_ms
_review_history: list[dict[str, Any]] = []

# Agent-run lifecycle tracking
_active: bool = False
_agent_name: str | None = None

_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


class DebateState:
    """Thread-safe accessor for debate-mode session state.

    All mutations go through :meth:`record_review` or :meth:`set_active`
    so that budget, loop-detection, and lifecycle counters stay consistent.
    """

    # ------------------------------------------------------------------
    # Budget & loop detection
    # ------------------------------------------------------------------

    @staticmethod
    def review_count() -> int:
        """Total reviews performed in this session."""
        with _lock:
            return _review_count

    @staticmethod
    def current_checkpoint() -> int:
        """Last checkpoint number the planner submitted."""
        with _lock:
            return _current_checkpoint

    @staticmethod
    def consecutive_revisions() -> int:
        """How many *revise* verdicts in a row at the current checkpoint."""
        with _lock:
            return _consecutive_revisions

    @staticmethod
    def remaining_budget() -> int:
        """How many more reviews are allowed this session."""
        with _lock:
            return max(0, get_debate_max_reviews() - _review_count)

    @staticmethod
    def is_budget_exhausted() -> bool:
        """True if the review budget has been consumed."""
        with _lock:
            return _review_count >= get_debate_max_reviews()

    @staticmethod
    def is_loop_detected() -> bool:
        """True if consecutive revisions exceed the loop threshold."""
        with _lock:
            return _consecutive_revisions >= get_debate_max_loops()

    @staticmethod
    def record_review(
        checkpoint: int,
        verdict_kind: VerdictKind,
        summary: str = "",
        latency_ms: float = 0.0,
    ) -> None:
        """Record a completed review and update all counters.

        Args:
            checkpoint: The checkpoint number the planner submitted.
            verdict_kind: The reviewer's verdict.
            summary: One-sentence summary from the reviewer.
            latency_ms: Wall-clock time of the review call in milliseconds.
        """
        global _review_count, _current_checkpoint
        global _consecutive_revisions, _last_verdict, _review_history

        with _lock:
            _review_count += 1
            _current_checkpoint = checkpoint
            _last_verdict = verdict_kind

            if verdict_kind == VerdictKind.REVISE:
                _consecutive_revisions += 1
            else:
                _consecutive_revisions = 0

            _review_history.append(
                {
                    "checkpoint": checkpoint,
                    "verdict": verdict_kind.value,
                    "summary": summary,
                    "latency_ms": round(latency_ms, 1),
                }
            )

    # ------------------------------------------------------------------
    # Agent-run lifecycle
    # ------------------------------------------------------------------

    @staticmethod
    def is_active() -> bool:
        """True if an agent run is currently in progress."""
        with _lock:
            return _active

    @staticmethod
    def agent_name() -> str | None:
        """Name of the currently running agent, or None."""
        with _lock:
            return _agent_name

    @staticmethod
    def set_active(active: bool, agent_name: str | None = None) -> None:
        """Mark an agent run as started or ended.

        Args:
            active: True when an agent run starts, False when it ends.
            agent_name: Name of the agent.  On end, only clears state
                if the name matches the currently active agent.
        """
        global _active, _agent_name

        with _lock:
            if active:
                _active = True
                _agent_name = agent_name
            elif agent_name is None or agent_name == _agent_name:
                # Clear only when no name given (force) or name matches
                _active = False
                _agent_name = None

    @staticmethod
    def review_history() -> list[dict[str, Any]]:
        """Return a snapshot of the review history for this session."""
        with _lock:
            return list(_review_history)

    # ------------------------------------------------------------------
    # Reset
    # ------------------------------------------------------------------

    @staticmethod
    def reset() -> None:
        """Reset all session state (used in tests or on shutdown)."""
        global _review_count, _current_checkpoint, _consecutive_revisions
        global _last_verdict, _active, _agent_name, _review_history

        with _lock:
            _review_count = 0
            _current_checkpoint = 0
            _consecutive_revisions = 0
            _last_verdict = None
            _active = False
            _agent_name = None
            _review_history = []
