"""Hybrid real tokenizer implementation for the token_accuracy plugin.

Primary: tiktoken for all OpenAI-family models (gpt-*, o3, o4, codex, etc.).
Fallbacks: provider-specific tokenizers (anthropic, sentencepiece),
then learned ratio (from token_ratio_learner), then improved heuristic.
"""

import logging

logger = logging.getLogger(__name__)

# Comprehensive tiktoken model mapping — maps substring matches to the
# closest tiktoken encoding name.  Order matters: longer/more specific
# keys should appear before shorter prefixes so they match first.
_TIKTOKEN_MODEL_MAP: dict[str, str] = {
    # --- OpenAI family (use real tiktoken encoding_for_model) ---
    "gpt-4.1-nano": "gpt-4o",
    "gpt-4.1-mini": "gpt-4o",
    "gpt-4.1": "gpt-4o",
    "gpt-4.5-preview": "gpt-4o",
    "gpt-4o-mini": "gpt-4o",
    "gpt-4o": "gpt-4o",
    "gpt-4-turbo": "gpt-4o",
    "gpt-4-32k": "gpt-4-32k",
    "gpt-4": "gpt-4",
    "gpt-5": "gpt-4o",
    "o3-mini": "gpt-4o",
    "o3": "gpt-4o",
    "o4-mini": "gpt-4o",
    "o4": "gpt-4o",
    "o1-preview": "gpt-4o",
    "o1-mini": "gpt-4o",
    "o1": "gpt-4o",
    "codex": "gpt-4o",
    "gpt-3.5-turbo": "gpt-3.5-turbo",
    # --- Anthropic (no native tiktoken — fall back to cl100k_base) ---
    "claude-4-opus": "cl100k_base",
    "claude-4-sonnet": "cl100k_base",
    "claude-sonnet-4": "cl100k_base",
    "claude-opus-4": "cl100k_base",
    "claude-3-5-sonnet": "cl100k_base",
    "claude-3-5-haiku": "cl100k_base",
    "claude-3-opus": "cl100k_base",
    "claude-3-sonnet": "cl100k_base",
    "claude-3-haiku": "cl100k_base",
    # --- Gemini (sentencepiece; tiktoken is just a rough proxy) ---
    "gemini-2.5": "cl100k_base",
    "gemini-2.0": "cl100k_base",
    "gemini-1.5": "cl100k_base",
    # --- DeepSeek ---
    "deepseek-chat": "cl100k_base",
    "deepseek": "cl100k_base",
    # --- Mistral / Mixtral / Codestral ---
    "codestral": "cl100k_base",
    "mixtral": "cl100k_base",
    "mistral-large": "cl100k_base",
    "mistral-medium": "cl100k_base",
    "mistral-small": "cl100k_base",
    "mistral": "cl100k_base",
    # --- xAI Grok ---
    "grok-3": "cl100k_base",
    "grok-2": "cl100k_base",
    "grok": "cl100k_base",
    # --- Cohere ---
    "command-r-plus": "cl100k_base",
    "command-r": "cl100k_base",
    "command": "cl100k_base",
    # --- Meta Llama ---
    "llama-4": "cl100k_base",
    "llama-3": "cl100k_base",
    "llama-2": "cl100k_base",
    "llama": "cl100k_base",
    # --- Google Gemma ---
    "gemma-3": "cl100k_base",
    "gemma-2": "cl100k_base",
    "gemma": "cl100k_base",
}

# Provider prefixes that map to a preferred fallback encoding when no
# substring in _TIKTOKEN_MODEL_MAP matches.
_PROVIDER_FALLBACK: dict[str, str] = {
    "claude-": "cl100k_base",
    "anthropic-": "cl100k_base",
    "gemini-": "cl100k_base",
    "deepseek": "cl100k_base",
    "mistral": "cl100k_base",
    "mixtral": "cl100k_base",
    "grok": "cl100k_base",
    "command": "cl100k_base",
    "llama": "cl100k_base",
    "gemma": "cl100k_base",
}


def _try_provider_tokenizer(model_name: str, text: str) -> int | None:
    """Attempt provider-native token counting; return count or None."""
    lowered = model_name.lower()
    # Anthropic: use their SDK's token counting if available
    if lowered.startswith(("claude-", "anthropic-")):
        try:
            import anthropic  # type: ignore[import-untyped]

            return anthropic.count_tokens(text)  # type: ignore[attr-defined]
        except Exception:
            return None
    # Gemini: use sentencepiece if available
    if lowered.startswith("gemini-"):
        try:
            import sentencepiece  # type: ignore[import-untyped]

            _sp = sentencepiece.SentencePieceProcessor()  # type: ignore[attr-defined]
            # Would need a model file — too heavy for inline use.
            return None
        except Exception:
            return None
    return None


def _get_tiktoken_encoder(model_name: str | None):
    try:
        import tiktoken

        if not model_name:
            return tiktoken.get_encoding("cl100k_base")

        lowered = model_name.lower()

        # 1. Exact / substring match against the comprehensive map
        for key, enc_name in _TIKTOKEN_MODEL_MAP.items():
            if key in lowered:
                try:
                    # For OpenAI-family encodings, use encoding_for_model
                    # for the most accurate BPE; for cl100k_base entries
                    # (non-OpenAI), go straight to get_encoding.
                    if enc_name == "cl100k_base":
                        return tiktoken.get_encoding("cl100k_base")
                    return tiktoken.encoding_for_model(enc_name)
                except Exception:
                    return tiktoken.get_encoding("cl100k_base")

        # 2. Provider-prefix fallback (e.g. "claude-4-maverick")
        for prefix, enc_name in _PROVIDER_FALLBACK.items():
            if lowered.startswith(prefix):
                try:
                    return tiktoken.get_encoding(enc_name)
                except Exception:
                    return tiktoken.get_encoding("cl100k_base")

        # 3. Catch-all — cl100k_base is the best universal proxy
        return tiktoken.get_encoding("cl100k_base")
    except ImportError:
        return None


def count_tokens(text: str, model: str | None = None) -> int:
    """Best-effort real token count.

    Resolution order:
      1. Provider-native tokenizer (anthropic SDK, sentencepiece)
      2. tiktoken (comprehensive model map → provider fallback → cl100k_base)
      3. Learned ratio (from token_ratio_learner plugin)
      4. Character-based heuristic (char/2.5)
    """
    if not text:
        return 0

    # 1. Try provider-native tokenizers first (most accurate)
    if model:
        native_count = _try_provider_tokenizer(model, text)
        if native_count is not None:
            return native_count

    # 2. tiktoken — comprehensive mapping with provider fallbacks
    encoder = _get_tiktoken_encoder(model)
    if encoder is not None:
        try:
            return len(encoder.encode(text))
        except Exception as e:
            logger.debug(f"tiktoken failed for {model}: {e}")

    # 3. Learned ratio (excellent for the user's usage patterns)
    try:
        from code_muse.plugins.token_ratio_learner.ratios import count_tokens as learned

        return learned(text, model=model)
    except Exception:
        pass

    # 4. Last resort — the original improved heuristic
    from code_muse.agents._history import estimate_tokens as heuristic

    return heuristic(text)
