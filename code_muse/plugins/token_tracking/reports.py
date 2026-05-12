"""Query and formatting functions for token tracking reports.

Provides ``gain_report``, ``cc_economics_report``, and ``session_report``.
"""

from code_muse.plugins.token_tracking.database import TrackingDatabase

# ------------------------------------------------------------------
# Time-range helpers
# ------------------------------------------------------------------

_TIME_RANGE_SQL = {
    "today": "date(timestamp) = date('now')",
    "week": "timestamp >= datetime('now', '-7 days')",
    "month": "timestamp >= datetime('now', '-30 days')",
    "all": "1=1",
}


def _time_filter(time_range: str) -> str:
    """Return a SQLite WHERE clause fragment for the given range."""
    return _TIME_RANGE_SQL.get(time_range, "1=1")


# ------------------------------------------------------------------
# Cost estimation
# ------------------------------------------------------------------


def _estimate_tokens_to_cost(input_tokens: int, output_tokens: int = 0) -> float:
    """Estimate Claude 3.5 Sonnet cost in USD.

    Pricing:
        * $3 / 1M input tokens
        * $15 / 1M output tokens
    """
    input_cost = input_tokens * 3.0 / 1_000_000
    output_cost = output_tokens * 15.0 / 1_000_000
    return input_cost + output_cost


# ------------------------------------------------------------------
# Reports
# ------------------------------------------------------------------


def gain_report(db: TrackingDatabase, time_range: str = "all") -> str:
    """Format a token-savings report.

    Args:
        db: A ``TrackingDatabase`` instance.
        time_range: One of ``today``, ``week``, ``month``, ``all``.

    Returns:
        Multi-line string suitable for display in the UI.
    """
    where = _time_filter(time_range)

    row = db.query_one(
        f"""
        SELECT
            COALESCE(SUM(raw_tokens), 0),
            COALESCE(SUM(compressed_tokens), 0),
            COUNT(*)
        FROM executions
        WHERE {where}
        """
    )
    total_raw, total_compressed, total_commands = row or (0, 0, 0)
    total_raw = int(total_raw)
    total_compressed = int(total_compressed)
    total_commands = int(total_commands)

    saved = total_raw - total_compressed
    savings_pct = (saved / max(total_raw, 1) * 100.0) if total_raw else 0.0

    top_strategies = db.query_all(
        f"""
        SELECT
            strategy,
            COUNT(*) AS cmd_count,
            COALESCE(SUM(raw_tokens - compressed_tokens), 0) AS saved_tokens
        FROM executions
        WHERE {where}
        GROUP BY strategy
        ORDER BY saved_tokens DESC
        LIMIT 5
        """
    )

    lines = [
        "Token Savings Report",
        f"Time range: {time_range}",
        f"Total commands: {total_commands}",
        f"Raw tokens: {total_raw} → Compressed tokens: {total_compressed}",
        f"Savings: {saved} tokens ({savings_pct:.1f}%)",
        "Top 5 strategies:",
    ]
    if top_strategies:
        for strategy, cmd_count, saved_tokens in top_strategies:
            lines.append(
                f"  {strategy}: {cmd_count} commands, {int(saved_tokens)} tokens saved"
            )
    else:
        lines.append("  (no data)")

    return "\n".join(lines)


def cc_economics_report(db: TrackingDatabase, time_range: str = "all") -> str:
    """Estimate dollar savings using Claude Code pricing.

    Treats raw tokens as "uncompressed input" and compressed tokens as
    "actual input after filtering".  Output tokens are not tracked
    separately so we only show input-side economics.

    Args:
        db: A ``TrackingDatabase`` instance.
        time_range: One of ``today``, ``week``, ``month``, ``all``.

    Returns:
        Compact, LLM-readable summary string.
    """
    where = _time_filter(time_range)

    row = db.query_one(
        f"""
        SELECT COALESCE(SUM(raw_tokens), 0), COALESCE(SUM(compressed_tokens), 0)
        FROM executions
        WHERE {where}
        """
    )
    total_raw, total_compressed = row or (0, 0)
    total_raw = int(total_raw)
    total_compressed = int(total_compressed)

    cost_uncompressed = _estimate_tokens_to_cost(total_raw, 0)
    cost_compressed = _estimate_tokens_to_cost(total_compressed, 0)
    savings = cost_uncompressed - cost_compressed

    lines = [
        "Claude Code Economics Report",
        f"Time range: {time_range}",
        f"Uncompressed input cost: ${cost_uncompressed:.4f}",
        f"Compressed input cost:   ${cost_compressed:.4f}",
        f"Estimated savings:       ${savings:.4f}",
    ]
    return "\n".join(lines)


def session_report(db: TrackingDatabase, limit: int = 10) -> str:
    """Report per-session adoption statistics.

    Args:
        db: A ``TrackingDatabase`` instance.
        limit: Maximum number of recent sessions to show.

    Returns:
        Multi-line string with adoption metrics per session.
    """
    sessions = db.query_all(
        """
        SELECT
            session_id,
            COUNT(*) AS total_commands,
            SUM(CASE WHEN strategy != 'unknown' THEN 1 ELSE 0 END) AS filtered_commands,
            MIN(timestamp) AS first_ts,
            MAX(timestamp) AS last_ts
        FROM executions
        GROUP BY session_id
        ORDER BY first_ts DESC
        LIMIT ?
        """,
        (limit,),
    )

    if not sessions:
        return "Session Report\n(no tracking data)"

    lines = ["Session Report"]
    total_adoption_sum = 0.0
    total_sessions = len(sessions)

    for session_id, total_cmds, filtered_cmds, first_ts, last_ts in sessions:
        total_cmds = int(total_cmds)
        filtered_cmds = int(filtered_cmds)
        adoption = (filtered_cmds / max(total_cmds, 1)) * 100.0
        total_adoption_sum += adoption

        flag = " ⚠️ low adoption" if adoption < 50 else ""
        lines.append(
            f"\nSession {session_id[:8]}…"
            f"\n  Commands: {total_cmds} total, {filtered_cmds} filtered"
            f"\n  Adoption: {adoption:.1f}%{flag}"
            f"\n  First: {first_ts}"
            f"\n  Last:  {last_ts}"
        )

    overall_avg = total_adoption_sum / max(total_sessions, 1)
    lines.append(f"\nOverall average adoption: {overall_avg:.1f}%")

    return "\n".join(lines)


# ------------------------------------------------------------------
# Edit efficiency report
# ------------------------------------------------------------------


def edit_efficiency_report(db: TrackingDatabase, time_range: str = "all") -> str:
    """Format an edit-efficiency / context-inflation report.

    Args:
        db: A ``TrackingDatabase`` instance.
        time_range: One of ``today``, ``week``, ``month``, ``all``.

    Returns:
        Multi-line string suitable for display in the UI.
    """
    edits = db.query_edit_summary(time_range)

    if not edits:
        range_label = {
            "today": "today",
            "week": "last 7 days",
            "month": "last 30 days",
            "all": "all time",
        }.get(time_range, time_range)
        return f"Edit Efficiency Report ({range_label})\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n(no edit tracking data)"

    total = len(edits)
    tool_counts: dict[str, int] = {}
    inflation_values: list[float] = []
    no_core_count = 0
    edits_with_inflation: list[tuple[float, str, int, int]] = []
    bucket_success: dict[str, list[tuple[int, int]]] = {
        "<4x": [],
        "4-10x": [],
        "10-25x": [],
        "25x+": [],
    }

    for edit in edits:
        tool = edit["tool_name"]
        tool_counts[tool] = tool_counts.get(tool, 0) + 1

        if edit["no_core_change"]:
            no_core_count += 1

        ratio = edit["inflation_ratio"]
        if ratio is not None:
            inflation_values.append(ratio)
            edits_with_inflation.append(
                (ratio, edit["file_path"], edit["total_edit_bytes"], edit["core_bytes"])
            )

            success = 1 if edit["success"] else 0
            if ratio < 4:
                bucket_success["<4x"].append((success, 1))
            elif ratio < 10:
                bucket_success["4-10x"].append((success, 1))
            elif ratio < 25:
                bucket_success["10-25x"].append((success, 1))
            else:
                bucket_success["25x+"].append((success, 1))
        else:
            # No core change — count in no_core bucket but don't show inflation
            pass

    range_label = {
        "today": "today",
        "week": "last 7 days",
        "month": "last 30 days",
        "all": "all time",
    }.get(time_range, time_range)

    lines = [
        f"Edit Efficiency Report ({range_label})",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"Total edit calls: {total}",
    ]
    for tool, count in sorted(tool_counts.items(), key=lambda x: -x[1]):
        lines.append(f"  • {tool}: {count}")

    lines.append("")
    lines.append("Context inflation:")

    if inflation_values:
        inflation_values.sort()
        median = inflation_values[len(inflation_values) // 2]
        p95_idx = int(len(inflation_values) * 0.95)
        p95 = inflation_values[min(p95_idx, len(inflation_values) - 1)]
        lines.append(f"  median inflation: {median:.2f}x")
        lines.append(f"  p95 inflation: {p95:.2f}x")
    else:
        lines.append("  median inflation: N/A")
        lines.append("  p95 inflation: N/A")

    lines.append(
        f"  no-core-change: {no_core_count} edits ({no_core_count / max(total, 1) * 100:.1f}%)"
    )

    # Worst offenders
    worst = sorted(edits_with_inflation, key=lambda x: -x[0])[:10]
    worst = [w for w in worst if w[0] > 20]
    if worst:
        lines.append("")
        lines.append("Worst offenders (>20x inflation):")
        for i, (ratio, path, total_bytes, core_bytes) in enumerate(worst, 1):
            lines.append(
                f"  {i}. {path} — {ratio:.1f}x ({total_bytes:,} bytes → {core_bytes:,} bytes core)"
            )

    # Failure rate by bucket
    lines.append("")
    lines.append("Failure rate by inflation bucket:")
    for bucket in ("<4x", "4-10x", "10-25x", "25x+"):
        entries = bucket_success[bucket]
        if entries:
            successes = sum(s for s, _ in entries)
            total_bucket = len(entries)
            rate = successes / total_bucket * 100
            lines.append(
                f"  {bucket}: {rate:.1f}% success ({successes}/{total_bucket})"
            )
        else:
            lines.append(f"  {bucket}: N/A")

    return "\n".join(lines)
