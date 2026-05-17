"""Context budget tracking and proactive warnings.

Tracks current token usage vs budget and emits warnings
at configurable thresholds so the user can act before
the hard pruning limit is hit.
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Default token budget (approximate context window) — used when
# get_model_context_length and drift tracker are both unavailable.
_DEFAULT_BUDGET_TOKENS = 128_000


def _resolve_budget_tokens() -> int:
    """Resolve the token budget with drift-correction when available.

    Resolution order:
      1. Get the model context length from config (if a model is set).
      2. If the drift tracker shows overestimation > 10%, apply a
         ``(1 - drift_pct)`` correction factor so budgets don't lie.
      3. Fall back to ``_DEFAULT_BUDGET_TOKENS``.
    """
    budget = _DEFAULT_BUDGET_TOKENS

    # Try to get the model's actual context length
    try:
        from code_muse.config.models import get_model_context_length

        budget = get_model_context_length()
    except Exception:
        pass

    # Apply drift correction if we're overestimating by more than 10%
    try:
        from code_muse.agents._history import get_drift_tracker

        tracker = get_drift_tracker()
        if (
            tracker.session_drift_pct > 0.10
            and tracker.total_estimated > tracker.total_actual
        ):
            correction = 1 - tracker.session_drift_pct
            budget = max(1, round(budget * correction))
            logger.debug(
                f"budget: applied drift correction {correction:.2f} "
                f"(drift_pct={tracker.session_drift_pct:.2%})"
            )
    except Exception:
        pass

    return budget


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

    budget = _resolve_budget_tokens()
    usage_pct = total_tokens / budget if budget > 0 else 0.0

    # Protected facts token accounting
    protected_facts_tokens = 0
    try:
        from code_muse.plugins.task_context.protected_facts import (
            get_protected_fact_manager,
        )

        mgr = get_protected_fact_manager()
        protected_facts_tokens = mgr.used_tokens
    except Exception:
        pass

    return {
        "total_tokens": total_tokens,
        "budget_tokens": budget,
        "usage_pct": usage_pct,
        "remaining_tokens": max(0, budget - total_tokens),
        "protected_facts_tokens": protected_facts_tokens,
        "protected_facts": get_fact_budget_info(),
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

    # Also check protected fact budget
    try:
        fb = get_fact_budget_info()
        if fb["usage_pct"] > 0.85 and not _warned_at_warn:
            from code_muse.messaging import emit_info

            emit_info(
                f"🛡️ Protected fact budget at {fb['usage_pct']:.0%} "
                f"({fb['fact_count']} facts, ~{fb['remaining']:,} tokens remaining). "
                f"Consider reviewing pinned facts with /task facts."
            )
    except Exception:
        pass


def get_fact_budget_info() -> dict:
    """Return current protected fact budget info."""
    from code_muse.plugins.task_context.protected_facts import (
        get_protected_fact_manager,
    )

    mgr = get_protected_fact_manager()
    return {
        "fact_count": len(mgr.get_all_facts()),
        "used_tokens": mgr.used_tokens,
        "max_budget": mgr.max_budget_tokens,
        "remaining": mgr.budget_remaining,
        "usage_pct": mgr.budget_used_pct,
    }


def reset_warning_flags() -> None:
    """Reset warning flags (e.g., after pruning or task complete)."""
    global _warned_at_warn, _warned_at_critical  # noqa: PLW0603
    _warned_at_warn = False
    _warned_at_critical = False
