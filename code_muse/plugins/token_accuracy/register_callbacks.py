"""Register callbacks for the token_accuracy plugin.

On startup it monkey-patches:
- code_muse.agents._history.estimate_tokens
- code_muse.agents._history.estimate_tokens_for_message

with a hybrid implementation that prefers real tokenizers (tiktoken first)
and falls back to learned ratio or heuristic.
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


def _on_startup() -> None:
    global _original_estimate_tokens, _original_estimate_tokens_for_message

    from code_muse.agents import _history

    _original_estimate_tokens = _history.estimate_tokens
    _history.estimate_tokens = _patched_estimate_tokens
    logger.info("token_accuracy: patched _history.estimate_tokens (hybrid/native)")

    _original_estimate_tokens_for_message = _history.estimate_tokens_for_message
    _history.estimate_tokens_for_message = _patched_estimate_tokens_for_message
    logger.info("token_accuracy: patched _history.estimate_tokens_for_message")


register_callback("startup", _on_startup)
