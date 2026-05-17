"""Context window resolution helpers, free of hardcoded defaults."""

import logging
from typing import Any

logger = logging.getLogger(__name__)


# Conservative default for completely unknown models
_FALLBACK_CONTEXT = 128_000


def get_context_limit(model_name: str | None = None) -> int:
    """Get the actual model context window for budget calculations.

    Centralizes resolution so all task_context code uses the same source of truth.

    Resolution order:
    1. Try code_muse.config.models.get_model_context_length(model_name)
    2. Fall back to get_model_context_length() without model_name
    3. Fall back to _FALLBACK_CONTEXT

    Args:
        model_name: Optional model name for per-model resolution.

    Returns:
        The context window size in tokens.
    """
    try:
        from code_muse.config.models import get_model_context_length

        if model_name:
            return int(get_model_context_length(model_name))
        return int(get_model_context_length())
    except Exception:
        logger.debug(
            "Failed to resolve context window, using fallback %d", _FALLBACK_CONTEXT
        )
        return _FALLBACK_CONTEXT


def get_effective_budget(model_name: str | None = None, overhead: int = 0) -> int:
    """Get the effective token budget for message history.

    Uses the same adaptive budget fractions as the core compaction system:
    - >= 1M: 88%
    - 100k - 1M: 74%
    - 32k - 100k: 68%
    - < 32k: 55%

    Args:
        model_name: Optional model name.
        overhead: System prompt + tool schema token overhead.

    Returns:
        Effective token budget available for message history.
    """
    from code_muse.config.models import compute_effective_history_budget

    max_ctx = get_context_limit(model_name)
    return compute_effective_history_budget(
        max_ctx, overhead=overhead, model_name=model_name
    )


# Cache the last resolved context to avoid repeated lookups
_last_resolved_context: dict[str, Any] = {
    "model": None,
    "context": None,
    "timestamp": 0.0,
}
_RESOLVE_CACHE_TTL = 30.0  # seconds


def get_cached_context_limit(model_name: str | None = None) -> int:
    """Get context limit with a short TTL cache to avoid redundant lookups."""
    import time

    global _last_resolved_context
    now = time.monotonic()
    cached = _last_resolved_context
    if cached["model"] == model_name and cached["timestamp"] + _RESOLVE_CACHE_TTL > now:
        return cached["context"]

    ctx = get_context_limit(model_name)
    _last_resolved_context = {
        "model": model_name,
        "context": ctx,
        "timestamp": now,
    }
    return ctx
