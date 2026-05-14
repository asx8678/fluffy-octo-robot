"""Session state management for the Debate Mode plugin.

Tracks per-session counters for budget enforcement and loop detection.
State is held in module-level variables — one session per Muse invocation.
"""

import threading

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

_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


class DebateState:
    """Thread-safe accessor for debate-mode session state.

    All mutations go through :meth:`record_review` so that budget and
    loop-detection counters stay consistent.
    """

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
    def record_review(checkpoint: int, verdict_kind: VerdictKind) -> None:
        """Record a completed review and update all counters.

        Args:
            checkpoint: The checkpoint number the planner submitted.
            verdict_kind: The reviewer's verdict.
        """
        global _review_count, _current_checkpoint, _consecutive_revisions, _last_verdict

        with _lock:
            _review_count += 1
            _current_checkpoint = checkpoint
            _last_verdict = verdict_kind

            if verdict_kind == VerdictKind.REVISE:
                _consecutive_revisions += 1
            else:
                _consecutive_revisions = 0

    @staticmethod
    def reset() -> None:
        """Reset all session state (used in tests or on shutdown)."""
        global _review_count, _current_checkpoint, _consecutive_revisions, _last_verdict

        with _lock:
            _review_count = 0
            _current_checkpoint = 0
            _consecutive_revisions = 0
            _last_verdict = None
