"""Telemetry for the Debate Mode plugin.

Tracks review latencies, verdict distributions, and budget utilisation.
Phase 3 will add persistent metrics; this scaffold logs basic events.
"""

import logging
import time
from typing import Any

from code_muse.plugins.debate.schemas import VerdictKind

logger = logging.getLogger(__name__)

# In-memory counters for the current session
_verdict_counts: dict[VerdictKind, int] = {
    VerdictKind.APPROVE: 0,
    VerdictKind.REVISE: 0,
    VerdictKind.REJECT: 0,
}
_total_latency_ms: float = 0.0


def record_review_latency(start_time: float, verdict_kind: VerdictKind) -> None:
    """Record the wall-clock time of a review call.

    Args:
        start_time: ``time.monotonic()`` taken before the review call.
        verdict_kind: The verdict returned by the reviewer.
    """
    global _total_latency_ms

    elapsed_ms = (time.monotonic() - start_time) * 1000
    _total_latency_ms += elapsed_ms
    _verdict_counts[verdict_kind] += 1

    logger.debug(
        "Review latency: %.1f ms  verdict: %s  session total: %.1f ms",
        elapsed_ms,
        verdict_kind.value,
        _total_latency_ms,
    )


def get_session_stats() -> dict[str, Any]:
    """Return a snapshot of telemetry for the current session."""
    total = sum(_verdict_counts.values())
    avg_ms = _total_latency_ms / total if total else 0.0
    return {
        "total_reviews": total,
        "verdict_counts": {k.value: v for k, v in _verdict_counts.items()},
        "avg_latency_ms": round(avg_ms, 1),
        "total_latency_ms": round(_total_latency_ms, 1),
    }
