"""Context budget tracking and proactive warnings.

Tracks current token usage vs budget and emits warnings
at configurable thresholds so the user can act before
the hard pruning limit is hit.
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Default token budget (approximate context window)
_DEFAULT_BUDGET_TOKENS = 128_000

# Track whether we've already warned at each threshold
_warned_at_warn = False
_warned_at_critical = False


def estimate_current_budget(message_history: list[Any]) -> dict:
    """Compute current budget usage from message history.

    Returns dict with: total_tokens, budget_tokens, usage_pct, remaining_tokens
    """
    from code_muse.agents._history import estimate_tokens_for_message
    from code_muse.plugins.task_context._text_utils import _extract_text

    total_tokens = 0
    for msg in message_history:
        # Use the proper per-message estimator when available,
        # fall back to text-based heuristic otherwise.
        try:
            total_tokens += estimate_tokens_for_message(msg)
        except Exception:
            text = _extract_text(msg)
            from code_muse.agents._history import estimate_tokens

            total_tokens += estimate_tokens(text)

    budget = _DEFAULT_BUDGET_TOKENS
    usage_pct = total_tokens / budget if budget > 0 else 0.0

    return {
        "total_tokens": total_tokens,
        "budget_tokens": budget,
        "usage_pct": usage_pct,
        "remaining_tokens": max(0, budget - total_tokens),
    }


def check_and_warn(
    budget_info: dict,
    warn_at: float = 0.65,
    critical_at: float = 0.85,
) -> None:
    """Emit proactive budget warnings at thresholds.

    Only warns once per threshold crossing (not every message).
    After crossing the critical threshold, the warn flag resets
    so that if the user prunes and usage drops below warn_at,
    they'll get re-warned on the way back up.
    """
    global _warned_at_warn, _warned_at_critical  # noqa: PLW0603

    usage = budget_info["usage_pct"]
    remaining = budget_info["remaining_tokens"]

    if usage >= critical_at and not _warned_at_critical:
        from code_muse.messaging import emit_warning

        emit_warning(
            f"🧠 Context budget at {usage:.0%}! "
            f"~{remaining:,} tokens remaining. "
            f"Consider completing tasks with /task complete or archiving old tasks."
        )
        _warned_at_critical = True
        # Reset warn flag so if they prune and it goes down, they can get re-warned
        _warned_at_warn = False

    elif usage >= warn_at and not _warned_at_warn:
        from code_muse.messaging import emit_info

        emit_info(
            f"🧠 Context budget at {usage:.0%} "
            f"(~{remaining:,} tokens remaining). "
            f"Tip: /task status to see task breakdown."
        )
        _warned_at_warn = True


def reset_warning_flags() -> None:
    """Reset warning flags (e.g., after pruning or task complete)."""
    global _warned_at_warn, _warned_at_critical  # noqa: PLW0603
    _warned_at_warn = False
    _warned_at_critical = False
