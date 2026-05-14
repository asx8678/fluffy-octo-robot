"""UI rendering for the Debate Mode plugin.

Displays review status and verdict information in the Muse terminal.
Phase 3 will add rich formatting; this scaffold provides minimal output.
"""

import logging

from code_muse.plugins.debate.schemas import VerdictKind

logger = logging.getLogger(__name__)

_VERDICT_EMOJI: dict[VerdictKind, str] = {
    VerdictKind.APPROVE: "✅",
    VerdictKind.REVISE: "🔄",
    VerdictKind.REJECT: "❌",
}


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
        f"{emoji} Debate review #{review_count}: {kind.value.upper()} — {summary} "
        f"[budget: {remaining_budget} remaining]"
    )
