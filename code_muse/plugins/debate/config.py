"""Configuration accessors for the Debate Mode plugin.

All settings read from ``muse.cfg`` via :func:`code_muse.config.get_value`.
Falling back to sensible defaults so the plugin works out-of-the-box.
"""

from code_muse.config import get_value, set_value

# ---------------------------------------------------------------------------
# Toggle
# ---------------------------------------------------------------------------


def is_debate_enabled() -> bool:
    """Check if debate mode is enabled (default: True)."""
    val = get_value("debate_enabled")
    if val is None:
        return True
    return str(val).lower() in ("1", "true", "yes", "on")


def set_debate_enabled(enabled: bool) -> None:
    """Persist the debate-mode toggle to ``muse.cfg``.

    Args:
        enabled: ``True`` to enable, ``False`` to disable.
    """
    set_value("debate_enabled", "true" if enabled else "false")


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------


def get_debate_reviewer_model() -> str | None:
    """Get the model to use as the reviewer, or None to use the global model."""
    return get_value("debate_reviewer_model")


# ---------------------------------------------------------------------------
# Budget
# ---------------------------------------------------------------------------


def get_debate_max_reviews() -> int:
    """Maximum number of reviews per session (default: 20)."""
    val = get_value("debate_max_reviews")
    if val is not None:
        try:
            return max(1, int(val))
        except (ValueError, TypeError):
            pass
    return 20


def get_debate_max_loops() -> int:
    """Maximum consecutive *revise* loops at a single checkpoint (default: 3).

    If the planner receives this many ``revise`` verdicts in a row without
    progress, the hook blocks further ``request_review`` calls.
    """
    val = get_value("debate_max_loops")
    if val is not None:
        try:
            return max(1, int(val))
        except (ValueError, TypeError):
            pass
    return 3
