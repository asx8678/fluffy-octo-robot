"""Telemetry for the Debate Mode plugin.

Tracks review latencies, verdict distributions, success rates, and
budget utilisation.  Supports NDJSON log persistence and in-memory
session snapshots.

Metrics collected:
    - Per-review wall-clock latency (ms)
    - Verdict distribution (approve / revise / reject counts)
    - Success rate (approve ÷ total)
    - Review breakdown by checkpoint
    - Session totals and averages

NDJSON logging:
    Each review is appended as a single JSON line to
    ``~/.muse/debate_telemetry.jsonl`` for offline analysis.
"""

import json
import logging
import time
from pathlib import Path
from typing import Any

from code_muse.config import paths as muse_paths
from code_muse.plugins.debate.schemas import VerdictKind

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# In-memory counters
# ---------------------------------------------------------------------------

_verdict_counts: dict[VerdictKind, int] = {
    VerdictKind.APPROVE: 0,
    VerdictKind.REVISE: 0,
    VerdictKind.REJECT: 0,
}
_total_latency_ms: float = 0.0
_min_latency_ms: float = float("inf")
_max_latency_ms: float = 0.0
_review_timestamps: list[float] = []  # monotonic timestamps for rate calc

# ---------------------------------------------------------------------------
# NDJSON log path
# ---------------------------------------------------------------------------


def _telemetry_log_path() -> Path:
    """Return the path to the NDJSON telemetry log file."""
    state_dir = getattr(muse_paths, "STATE_DIR", None)
    if state_dir is None:
        # Fallback: ~/.muse/state/
        state_dir = Path.home() / ".muse" / "state"
    return Path(state_dir) / "debate_telemetry.jsonl"


# ---------------------------------------------------------------------------
# Core recording
# ---------------------------------------------------------------------------


def record_review_latency(start_time: float, verdict_kind: VerdictKind) -> None:
    """Record the wall-clock time of a review call.

    Updates in-memory counters and appends an NDJSON entry to the log.

    Args:
        start_time: ``time.monotonic()`` taken before the review call.
        verdict_kind: The verdict returned by the reviewer.
    """
    global _total_latency_ms, _min_latency_ms, _max_latency_ms

    elapsed_ms = (time.monotonic() - start_time) * 1000
    _total_latency_ms += elapsed_ms
    _verdict_counts[verdict_kind] += 1
    _review_timestamps.append(time.monotonic())

    if elapsed_ms < _min_latency_ms:
        _min_latency_ms = elapsed_ms
    if elapsed_ms > _max_latency_ms:
        _max_latency_ms = elapsed_ms

    logger.debug(
        "Review latency: %.1f ms  verdict: %s  session total: %.1f ms",
        elapsed_ms,
        verdict_kind.value,
        _total_latency_ms,
    )

    # Append NDJSON entry
    _append_ndjson_entry(elapsed_ms, verdict_kind)


def _append_ndjson_entry(elapsed_ms: float, verdict_kind: VerdictKind) -> None:
    """Append a single NDJSON line to the telemetry log file."""
    entry = {
        "timestamp": time.time(),
        "elapsed_ms": round(elapsed_ms, 1),
        "verdict": verdict_kind.value,
        "session_stats": get_session_stats(),
    }
    try:
        log_path = _telemetry_log_path()
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, default=str) + "\n")
    except OSError:
        logger.debug("Could not write telemetry NDJSON entry")


# ---------------------------------------------------------------------------
# Session stats
# ---------------------------------------------------------------------------


def get_session_stats() -> dict[str, Any]:
    """Return a snapshot of telemetry for the current session.

    Includes total reviews, verdict counts, average/min/max latency,
    and success rate.
    """
    total = sum(_verdict_counts.values())
    avg_ms = _total_latency_ms / total if total else 0.0
    approve_count = _verdict_counts[VerdictKind.APPROVE]
    success_rate = approve_count / total if total else 0.0

    # Review rate (reviews per minute) based on first and last timestamps
    rate = 0.0
    if len(_review_timestamps) >= 2:
        span_sec = _review_timestamps[-1] - _review_timestamps[0]
        rate = (total - 1) / (span_sec / 60) if span_sec > 0 else 0.0

    return {
        "total_reviews": total,
        "verdict_counts": {k.value: v for k, v in _verdict_counts.items()},
        "success_rate": round(success_rate, 3),
        "avg_latency_ms": round(avg_ms, 1),
        "min_latency_ms": round(_min_latency_ms, 1) if total else 0.0,
        "max_latency_ms": round(_max_latency_ms, 1) if total else 0.0,
        "total_latency_ms": round(_total_latency_ms, 1),
        "reviews_per_minute": round(rate, 2),
    }


def get_verdict_breakdown() -> dict[str, int]:
    """Return verdict counts as a simple ``{kind: count}`` dict."""
    return {k.value: v for k, v in _verdict_counts.items()}


def get_latency_stats() -> dict[str, float]:
    """Return latency statistics (avg, min, max, total) in ms."""
    total = sum(_verdict_counts.values())
    return {
        "avg_ms": round(_total_latency_ms / total, 1) if total else 0.0,
        "min_ms": round(_min_latency_ms, 1) if total else 0.0,
        "max_ms": round(_max_latency_ms, 1) if total else 0.0,
        "total_ms": round(_total_latency_ms, 1),
    }


def get_success_rate() -> float:
    """Return the fraction of reviews that returned *approve*."""
    total = sum(_verdict_counts.values())
    if total == 0:
        return 0.0
    return round(_verdict_counts[VerdictKind.APPROVE] / total, 3)


# ---------------------------------------------------------------------------
# Reset (for tests and /debate reset)
# ---------------------------------------------------------------------------


def reset_telemetry() -> None:
    """Reset all in-memory telemetry counters."""
    global _total_latency_ms, _min_latency_ms, _max_latency_ms

    _verdict_counts[VerdictKind.APPROVE] = 0
    _verdict_counts[VerdictKind.REVISE] = 0
    _verdict_counts[VerdictKind.REJECT] = 0
    _total_latency_ms = 0.0
    _min_latency_ms = float("inf")
    _max_latency_ms = 0.0
    _review_timestamps.clear()
