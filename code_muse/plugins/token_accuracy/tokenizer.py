"""Hybrid real tokenizer implementation for the token_accuracy plugin.

Primary: tiktoken for all OpenAI-family models (gpt-*, o3, o4, codex, etc.).
Fallbacks: learned ratio (from token_ratio_learner), then improved heuristic.
"""

import logging

logger = logging.getLogger(__name__)

# Simple mapping for tiktoken — we use a safe common encoding for most modern models
_TIKTOKEN_MODEL_MAP = {
    "gpt-4o": "gpt-4o",
    "gpt-4.1": "gpt-4o",
    "gpt-4-turbo": "gpt-4o",
    "o3": "gpt-4o",
    "o4": "gpt-4o",
    "codex": "gpt-4o",
    "gpt-5": "gpt-4o",
}


def _get_tiktoken_encoder(model_name: str | None):
    try:
        import tiktoken

        if not model_name:
            return tiktoken.get_encoding("cl100k_base")

        lowered = model_name.lower()
        for key, enc_name in _TIKTOKEN_MODEL_MAP.items():
            if key in lowered:
                try:
                    return tiktoken.encoding_for_model(enc_name)
                except Exception:
                    return tiktoken.get_encoding("cl100k_base")
        return tiktoken.get_encoding("cl100k_base")
    except ImportError:
        return None


def count_tokens(text: str, model: str | None = None) -> int:
    """Best-effort real token count.

    Tries tiktoken for OpenAI-family models first.
    Falls back to learned ratio, then the original heuristic.
    """
    if not text:
        return 0

    encoder = _get_tiktoken_encoder(model)
    if encoder is not None:
        try:
            return len(encoder.encode(text))
        except Exception as e:
            logger.debug(f"tiktoken failed for {model}: {e}")

    # Fallback to learned ratio (excellent for the user's usage patterns)
    try:
        from code_muse.plugins.token_ratio_learner.ratios import count_tokens as learned

        return learned(text, model=model)
    except Exception:
        pass

    # Last resort — the original improved heuristic
    from code_muse.agents._history import estimate_tokens as heuristic

    return heuristic(text)
