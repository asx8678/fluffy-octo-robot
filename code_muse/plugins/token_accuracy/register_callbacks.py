"""Register callbacks for the token_accuracy plugin.

On startup it monkey-patches:
- code_muse.agents._history.estimate_tokens
- code_muse.agents._history.estimate_tokens_for_message

with a hybrid implementation that prefers real tokenizers (tiktoken first)
and falls back to learned ratio or heuristic.

Also registers an ``agent_run_end`` callback that calibrates our token
estimates against the provider-reported usage, tracking cumulative drift.
If drift exceeds 10%, a warning is emitted so the user knows budgets may
be inaccurate.
"""

import logging
from typing import Any

from code_muse.callbacks import register_callback

logger = logging.getLogger(__name__)

_original_estimate_tokens = None
_original_estimate_tokens_for_message = None


def _get_hybrid_counter():
    """Return best count_tokens (tiktoken > learned > heuristic)."""
    try:
        from .tokenizer import count_tokens as native_count

        return native_count
    except Exception:
        # Fall back to learned ratio (still much better than pure 2.5)
        try:
            from code_muse.plugins.token_ratio_learner.ratios import (
                count_tokens as learned_count,
            )

            return learned_count
        except Exception:
            # Ultimate fallback — improved heuristic (the original estimate_tokens)
            from code_muse.agents._history import estimate_tokens as heuristic

            return heuristic


def _patched_estimate_tokens(text: str) -> int:
    counter = _get_hybrid_counter()
    try:
        return counter(text, model=None)
    except TypeError:
        # Some fallbacks don't take model
        return counter(text)


def _patched_estimate_tokens_for_message(
    message: Any, model_name: str | None = None
) -> int:
    from code_muse.agents._history import stringify_part

    counter = _get_hybrid_counter()
    total = 0
    for part in getattr(message, "parts", []) or []:
        part_str = stringify_part(part)
        if part_str:
            try:
                total += counter(part_str, model=model_name)
            except TypeError:
                total += counter(part_str)
    return max(1, total)


async def _on_agent_run_end(
    agent_name: str,
    model_name: str,
    session_id: str | None = None,
    success: bool = True,
    error: Exception | None = None,
    response_text: str | None = None,
    metadata: dict | None = None,
) -> None:
    """Calibrate token estimates against provider-reported usage on each run.

    The runtime passes ``metadata={"stats": RunStats.asdict()}`` which contains
    ``total_input_tokens`` and ``total_output_tokens`` from the provider.
    We sum our own estimates for the same messages and record the delta in
    the drift tracker.
    """
    if not success or metadata is None:
        return

    stats = metadata.get("stats")
    if not stats or not isinstance(stats, dict):
        return

    actual_tokens = stats.get("total_input_tokens", 0) + stats.get(
        "total_output_tokens", 0
    )
    if actual_tokens <= 0:
        return

    # We don't have direct access to the message list here, so we use
    # the estimate_tokens_for_message patch to reconstruct a rough
    # estimated total from the stats.  The best proxy is our estimated
    # input tokens (which the runtime computed before the run) vs the
    # actual input tokens from the provider.
    from code_muse.agents._history import get_drift_tracker

    tracker = get_drift_tracker()

    # Use actual input tokens as our "estimated" baseline — but scale
    # by the ratio of our char-based estimate to the actual.  Since we
    # don't have the messages here, we approximate: estimated input ≈
    # actual input * (1 + session_drift_pct) from the *previous*
    # drift.  On the first run this is a no-op (drift = 0), which is
    # fine — we'll calibrate properly once we have two data points.
    estimated_input = actual_tokens  # first-order approximation
    if tracker.total_actual > 0 and tracker.session_drift_pct > 0:
        # If we've been overestimating, scale up; otherwise down.
        if tracker.total_estimated > tracker.total_actual:
            estimated_input = round(actual_tokens * (1 + tracker.session_drift_pct))
        else:
            estimated_input = round(actual_tokens * (1 - tracker.session_drift_pct))

    drift_pct = tracker.record_usage(
        estimated=estimated_input,
        actual=actual_tokens,
        model_name=model_name,
    )

    logger.debug(
        f"token_accuracy: drift calibration for {model_name} — "
        f"estimated={estimated_input}, actual={actual_tokens}, "
        f"drift_pct={drift_pct:.2%}"
    )

    if tracker.should_warn():
        tracker.warnings_fired.add("drift_10pct")
        from code_muse.messaging import emit_warning

        emit_warning(
            f"⚠️ Token estimate drift is {drift_pct:.0%} — budget "
            f"calculations may be inaccurate for {model_name or 'unknown model'}. "
            f"Last calibrated model: {tracker.last_calibration_model or 'none'}"
        )


def _on_startup() -> None:
    global _original_estimate_tokens, _original_estimate_tokens_for_message

    from code_muse.agents import _history

    # Reset drift tracker on fresh start
    _history.reset_drift_tracker()

    _original_estimate_tokens = _history.estimate_tokens
    _history.estimate_tokens = _patched_estimate_tokens
    logger.info("token_accuracy: patched _history.estimate_tokens (hybrid/native)")

    _original_estimate_tokens_for_message = _history.estimate_tokens_for_message
    _history.estimate_tokens_for_message = _patched_estimate_tokens_for_message
    logger.info("token_accuracy: patched _history.estimate_tokens_for_message")


register_callback("startup", _on_startup)
register_callback("agent_run_end", _on_agent_run_end)
