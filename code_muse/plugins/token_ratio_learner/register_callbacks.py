"""Register callbacks for the token-ratio-learner plugin.

On startup, monkeypatches:
1. ``_history.estimate_tokens`` — uses learned ratio instead of hardcoded /2.5
2. ``_history.estimate_tokens_for_message`` — per-part learned estimation
3. ``_runtime.run`` — wraps to record ratios from actual API responses
"""

import logging
from typing import Any

from code_muse.callbacks import register_callback

logger = logging.getLogger(__name__)

_original_estimate_tokens = None
_original_estimate_tokens_for_message = None
_original_run = None


def _patched_estimate_tokens(text: str) -> int:
    from code_muse.plugins.token_ratio_learner.ratios import count_tokens

    return count_tokens(text, model=None)


def _patched_estimate_tokens_for_message(
    message: Any,
    model_name: str | None = None,
) -> int:
    from code_muse.agents._history import stringify_part
    from code_muse.plugins.token_ratio_learner.ratios import count_tokens

    total = 0
    for part in getattr(message, "parts", []) or []:
        part_str = stringify_part(part)
        if part_str:
            total += count_tokens(part_str, model=model_name)
    return max(1, total)


def _compute_input_char_count(agent: Any, prompt: Any) -> int:
    char_count = 0
    if isinstance(prompt, str):
        char_count += len(prompt)
    elif isinstance(prompt, list):
        for item in prompt:
            if isinstance(item, str):
                char_count += len(item)
    try:
        from code_muse.agents._history import stringify_part

        for msg in agent._message_history:
            for part in getattr(msg, "parts", []) or []:
                part_str = stringify_part(part)
                if part_str:
                    char_count += len(part_str)
    except Exception:
        pass
    return char_count


async def _patched_run(
    agent: Any,
    prompt: str,
    *,
    attachments: Any = None,
    link_attachments: Any = None,
    output_type: Any = None,
    **kwargs: Any,
) -> Any:
    global _original_run

    input_char_count = _compute_input_char_count(agent, prompt)

    result = await _original_run(
        agent,
        prompt,
        attachments=attachments,
        link_attachments=link_attachments,
        output_type=output_type,
        **kwargs,
    )

    try:
        usage = (
            result.usage()
            if callable(getattr(result, "usage", None))
            else getattr(result, "usage", None)
        )
        input_tokens = getattr(usage, "input_tokens", 0) or getattr(
            usage, "request_tokens", 0
        )
        if input_tokens > 0 and input_char_count > 0:
            from code_muse.plugins.token_ratio_learner.ratios import _record_token_ratio

            model = agent.get_model_name()
            if model:
                _record_token_ratio(model, input_char_count, input_tokens)
    except Exception:
        pass

    return result


def _on_startup() -> None:
    global _original_estimate_tokens, _original_estimate_tokens_for_message
    global _original_run

    from code_muse.agents import _history, _runtime

    _original_estimate_tokens = _history.estimate_tokens
    _history.estimate_tokens = _patched_estimate_tokens
    logger.info("token_ratio_learner: patched _history.estimate_tokens")

    _original_estimate_tokens_for_message = _history.estimate_tokens_for_message
    _history.estimate_tokens_for_message = _patched_estimate_tokens_for_message
    logger.info("token_ratio_learner: patched _history.estimate_tokens_for_message")

    _original_run = _runtime.run
    _runtime.run = _patched_run
    logger.info("token_ratio_learner: patched _runtime.run")


register_callback("startup", _on_startup)
