"""Context budget tracking and proactive warnings.

Tracks current token usage vs budget and emits warnings
at configurable thresholds so the user can act before
the hard pruning limit is hit.

Now model-aware: budget_tokens is resolved from the actual model context
window instead of a hardcoded 128k default.
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)


def _resolve_budget_tokens(model_name: str | None = None) -> int:
    """Resolve the actual token budget from model context + drift correction.

    Resolution:
    1. Get model context limit (via centralized _context_utils)
    2. Apply drift correction if token calibration shows overestimation > 10%
    3. Fall back to 128k (conservative)

    Args:
        model_name: Optional model name for context-aware budget resolution.

    Returns:
        Token budget for the model's context window.
    """
    try:
        from code_muse.plugins.task_context._context_utils import (
            get_cached_context_limit,
        )

        base = get_cached_context_limit(model_name)

        # Apply drift correction if available
        try:
            from code_muse.agents._history import get_drift_tracker

            tracker = get_drift_tracker()
            drift = tracker.session_drift_pct
            if drift > 0.10:  # Only correct if significant overestimation
                correction = 1.0 - min(drift, 0.50)  # Max 50% correction
                base = max(4096, int(base * correction))
        except Exception:
            pass

        return max(4096, base)
    except Exception:
        logger.debug("Budget resolution failed, using fallback 128k")
        return 128_000


# Track whether we've already warned at each threshold
_warned_at_warn = False
_warned_at_critical = False


def estimate_current_budget(
    message_history: list[Any],
    model_name: str | None = None,
) -> dict:
    """Compute current budget usage from message history.

    Now model-aware: budget_tokens is resolved from the actual model context
    window instead of a hardcoded 128k default.

    Args:
        message_history: The current message history.
        model_name: Optional model name for context-aware budget resolution.

    Returns dict with: total_tokens, budget_tokens, usage_pct, remaining_tokens,
    protected_facts_tokens, protected_facts (if protected facts plugin loaded).
    """
    from code_muse.agents._history import estimate_tokens_for_message
    from code_muse.plugins.task_context._text_utils import _extract_text

    total_tokens = 0
    for msg in message_history:
        try:
            total_tokens += estimate_tokens_for_message(msg)
        except Exception:
            text = _extract_text(msg)
            from code_muse.agents._history import estimate_tokens

            total_tokens += estimate_tokens(text)

    budget = _resolve_budget_tokens(model_name)
    usage_pct = total_tokens / budget if budget > 0 else 0.0

    result = {
        "total_tokens": total_tokens,
        "budget_tokens": budget,
        "model_name": model_name,
        "usage_pct": usage_pct,
        "remaining_tokens": max(0, budget - total_tokens),
        "protected_facts_tokens": 0,
        "protected_facts": [],
    }

    # Include protected fact info if available
    try:
        from code_muse.plugins.task_context.protected_facts import (
            get_protected_fact_manager,
        )

        mgr = get_protected_fact_manager()
        result["protected_facts_tokens"] = mgr.used_tokens
        result["protected_facts"] = [
            {
                "content": f.content,
                "category": f.category,
                "tokens": f.token_cost,
            }
            for f in mgr.get_all_facts()
        ]
    except Exception:
        pass

    return result


def check_and_warn(
    budget_info: dict,
    warn_at: float = 0.65,
    critical_at: float = 0.85,
    model_name: str | None = None,
) -> None:
    """Emit proactive budget warnings at thresholds.

    Now model-aware: budgets are calibrated to the actual model context window.
    Only warns once per threshold crossing (not every message).
    After crossing the critical threshold, the warn flag resets
    so that if the user prunes and usage drops below warn_at,
    they'll get re-warned on the way back up.
    """
    global _warned_at_warn, _warned_at_critical  # noqa: PLW0603

    usage = budget_info["usage_pct"]
    remaining = budget_info["remaining_tokens"]
    budget_tokens = budget_info.get("budget_tokens", 0)

    # Log model context for debugging
    if model_name:
        logger.debug(
            "Budget check: model=%s, budget=%d, usage=%.1f%%",
            model_name,
            budget_tokens,
            usage * 100,
        )

    if usage >= critical_at and not _warned_at_critical:
        from code_muse.messaging import emit_warning

        model_info = f" ({model_name})" if model_name else ""
        emit_warning(
            f"🧠 Context budget at {usage:.0%}{model_info}! "
            f"~{remaining:,} tokens remaining (budget: {budget_tokens:,}). "
            f"Consider completing tasks with /task complete or archiving old tasks."
        )
        _warned_at_critical = True
        # Reset warn flag so if they prune and it goes down, they can get re-warned
        _warned_at_warn = False

    elif usage >= warn_at and not _warned_at_warn:
        from code_muse.messaging import emit_info

        model_info = f" ({model_name})" if model_name else ""
        emit_info(
            f"🧠 Context budget at {usage:.0%}{model_info} "
            f"(~{remaining:,} tokens remaining, budget: {budget_tokens:,}). "
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
