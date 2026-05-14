"""UI rendering for the Debate Mode plugin.

Displays review status, verdict information, progress bars, and
review history in the Muse terminal using standard emit functions.

Rendering functions:
    - :func:`show_reviewing` — progress indicator while a review runs
    - :func:`show_verdict` — rich verdict display with issues list
    - :func:`render_verdict_summary` — one-line verdict summary
    - :func:`render_progress_bar` — budget utilisation bar
    - :func:`render_review_history` — tabular review history
    - :func:`render_status_panel` — full status overview
"""

import logging

from code_muse.plugins.debate.schemas import VerdictKind

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Emoji / colour mappings
# ---------------------------------------------------------------------------

_VERDICT_EMOJI: dict[VerdictKind, str] = {
    VerdictKind.APPROVE: "✅",
    VerdictKind.REVISE: "🔄",
    VerdictKind.REJECT: "❌",
}

_VERDICT_LABEL: dict[VerdictKind, str] = {
    VerdictKind.APPROVE: "APPROVE",
    VerdictKind.REVISE: "REVISE",
    VerdictKind.REJECT: "REJECT",
}

_SEVERITY_EMOJI: dict[str, str] = {
    "critical": "🔴",
    "warning": "🟡",
    "info": "🔵",
}

_BAR_FILLED = "█"
_BAR_EMPTY = "░"


# ---------------------------------------------------------------------------
# Progress indicator
# ---------------------------------------------------------------------------


def show_reviewing(checkpoint: int, proposal_preview: str = "") -> str:
    """Return a progress message shown while a review is in-flight.

    Args:
        checkpoint: The checkpoint number being reviewed.
        proposal_preview: First ~80 chars of the proposal (optional).

    Returns:
        A formatted string suitable for ``emit_info``.
    """
    preview = ""
    if proposal_preview:
        # Truncate and strip newlines for one-line display
        short = proposal_preview.replace("\n", " ")[:80]
        preview = f" — {short}…"
    return f"🔍 Debating checkpoint {checkpoint}{preview}"


# ---------------------------------------------------------------------------
# Verdict display
# ---------------------------------------------------------------------------


def show_verdict(
    kind: VerdictKind,
    summary: str,
    issues: list[dict] | None = None,
    confidence: float = 0.0,
    review_count: int = 0,
    remaining_budget: int = 0,
) -> str:
    """Return a rich, multi-line verdict display.

    Includes the verdict emoji, summary, confidence bar, issue list,
    and budget status.

    Args:
        kind: The verdict decision.
        summary: One-sentence summary from the reviewer.
        issues: List of issue dicts (severity, message, suggestion).
        confidence: Reviewer confidence (0–1).
        review_count: Total reviews in this session.
        remaining_budget: Reviews remaining before exhaustion.

    Returns:
        A formatted string suitable for ``emit_info`` / ``emit_success``.
    """
    emoji = _VERDICT_EMOJI.get(kind, "📝")
    label = _VERDICT_LABEL.get(kind, kind.value.upper())

    lines: list[str] = []
    lines.append(f"{emoji} {label} — {summary}")

    # Confidence bar
    filled = int(confidence * 10)
    bar = _BAR_FILLED * filled + _BAR_EMPTY * (10 - filled)
    lines.append(f"   Confidence: {bar} {confidence:.0%}")

    # Issues
    if issues:
        lines.append("   Issues:")
        for issue in issues[:5]:  # Cap at 5 to keep display manageable
            sev = issue.get("severity", "info")
            msg = issue.get("message", "")
            sev_emoji = _SEVERITY_EMOJI.get(sev, "•")
            line = f"     {sev_emoji} [{sev}] {msg}"
            suggestion = issue.get("suggestion")
            if suggestion:
                line += f" → {suggestion}"
            lines.append(line)
        if len(issues) > 5:
            lines.append(f"     … and {len(issues) - 5} more")

    # Budget
    lines.append(
        f"   Budget: {remaining_budget} remaining ({review_count} reviews used)"
    )

    return "\n".join(lines)


def render_verdict_summary(
    kind: VerdictKind,
    summary: str,
    review_count: int,
    remaining_budget: int,
) -> str:
    """Return a one-line verdict summary for terminal display.

    Args:
        kind: The verdict decision.
        summary: The reviewer's one-sentence summary.
        review_count: Total reviews in this session.
        remaining_budget: Reviews remaining before budget exhaustion.

    Returns:
        A formatted string suitable for ``emit_info`` / ``emit_success``.
    """
    emoji = _VERDICT_EMOJI.get(kind, "📝")
    return (
        f"{emoji} Debate review #{review_count}: "
        f"{kind.value.upper()} — {summary} "
        f"[budget: {remaining_budget} remaining]"
    )


# ---------------------------------------------------------------------------
# Progress bar
# ---------------------------------------------------------------------------


def render_progress_bar(
    used: int,
    total: int,
    width: int = 20,
) -> str:
    """Return a text progress bar showing budget utilisation.

    Args:
        used: Number of reviews consumed.
        total: Maximum reviews allowed.
        width: Character width of the bar.

    Returns:
        A string like ``████████░░░░░░░░ 8/20``.
    """
    if total <= 0:
        return f"{_BAR_EMPTY * width} 0/0"

    filled = min(width, int(used / total * width))
    bar = _BAR_FILLED * filled + _BAR_EMPTY * (width - filled)
    pct = used / total * 100
    return f"{bar} {used}/{total} ({pct:.0f}%)"


# ---------------------------------------------------------------------------
# Review history
# ---------------------------------------------------------------------------


def render_review_history(history: list[dict]) -> str:
    """Return a formatted review history table.

    Args:
        history: List of review dicts (checkpoint, verdict, summary, latency_ms).

    Returns:
        A formatted string with one review per line.
    """
    if not history:
        return "📋 No reviews in this session yet."

    lines = ["📋 Review History:"]
    lines.append("   #  │ Ckpt │ Verdict │ Latency │ Summary")
    lines.append("  ────┼──────┼─────────┼─────────┼────────")

    for i, entry in enumerate(history, 1):
        ckpt = entry.get("checkpoint", "?")
        verdict = entry.get("verdict", "?")
        latency = entry.get("latency_ms", 0)
        summary = entry.get("summary", "").replace("\n", " ")[:40]
        emoji = _VERDICT_EMOJI.get(VerdictKind(verdict), "•")
        lines.append(
            f"  {i:>3} │ {ckpt:>4} │ {emoji} {verdict:<6} │ "
            f"{latency:>6.0f}ms │ {summary}"
        )

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Status panel
# ---------------------------------------------------------------------------


def render_status_panel(
    enabled: bool,
    active: bool,
    agent_name: str | None,
    review_count: int,
    remaining_budget: int,
    max_reviews: int,
    consecutive_revisions: int,
    max_loops: int,
    avg_latency_ms: float,
) -> str:
    """Return a comprehensive status panel for ``/debate status``.

    Args:
        enabled: Whether debate mode is currently enabled.
        active: Whether an agent run is in progress.
        agent_name: Name of the active agent, or None.
        review_count: Total reviews performed.
        remaining_budget: Reviews remaining.
        max_reviews: Maximum reviews allowed.
        consecutive_revisions: Current consecutive-revision count.
        max_loops: Maximum consecutive revisions before loop detection.
        avg_latency_ms: Average review latency.

    Returns:
        A formatted multi-line status string.
    """
    status = "ON" if enabled else "OFF"
    active_str = f"active ({agent_name})" if active else "idle"

    lines = [
        f"⚖️  Debate Mode: {status}",
        f"   Agent: {active_str}",
        f"   Budget: {render_progress_bar(review_count, max_reviews)}",
        f"   Remaining: {remaining_budget}/{max_reviews}",
        f"   Loop risk: {consecutive_revisions}/{max_loops} consecutive revisions",
        f"   Avg latency: {avg_latency_ms:.0f}ms",
    ]

    return "\n".join(lines)
