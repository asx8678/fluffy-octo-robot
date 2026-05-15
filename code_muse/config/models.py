"""Config: model selection, validation, and caching."""

import configparser

import code_muse.config.parser as _parser
import code_muse.config.paths as paths

# Session-local model name (initialized from file on first access, then cached)
_SESSION_MODEL: str | None = None

# Cache containers for model validation and defaults
_model_validation_cache = {}
_default_model_cache = None
_default_vision_model_cache = None


def _default_model_from_models_json():
    """Load the default model name from models.json.

    Returns the first model in models.json as the default.
    Falls back to ``gpt-5`` if the file cannot be read.
    """
    global _default_model_cache

    if _default_model_cache is not None:
        return _default_model_cache

    try:
        from code_muse.model_factory import ModelFactory

        models_config = ModelFactory.load_config()
        if models_config:
            # Use first model in models.json as default
            first_key = next(iter(models_config))
            _default_model_cache = first_key
            return first_key
        _default_model_cache = "gpt-5"
        return "gpt-5"
    except Exception:
        _default_model_cache = "gpt-5"
        return "gpt-5"


def _default_vision_model_from_models_json() -> str:
    """Select a default vision-capable model from models.json with caching."""
    global _default_vision_model_cache

    if _default_vision_model_cache is not None:
        return _default_vision_model_cache

    try:
        from code_muse.model_factory import ModelFactory

        models_config = ModelFactory.load_config()
        if models_config:
            # Prefer explicitly tagged vision models
            for name, config in models_config.items():
                if config.get("supports_vision"):
                    _default_vision_model_cache = name
                    return name

            # Fallback heuristic: common multimodal models
            preferred_candidates = (
                "gpt-4.1",
                "gpt-4.1-mini",
                "gpt-4.1-nano",
                "claude-4-0-sonnet",
                "gemini-2.5-flash-preview-05-20",
            )
            for candidate in preferred_candidates:
                if candidate in models_config:
                    _default_vision_model_cache = candidate
                    return candidate

            # Last resort: use the general default model
            _default_vision_model_cache = _default_model_from_models_json()
            return _default_vision_model_cache

        _default_vision_model_cache = "gpt-4.1"
        return "gpt-4.1"
    except Exception:
        _default_vision_model_cache = "gpt-4.1"
        return "gpt-4.1"


def _validate_model_exists(model_name: str) -> bool:
    """Check if a model exists in models.json with caching to avoid redundant calls."""
    global _model_validation_cache

    # Check cache first
    if model_name in _model_validation_cache:
        return _model_validation_cache[model_name]

    try:
        from code_muse.model_factory import ModelFactory

        models_config = ModelFactory.load_config()
        exists = model_name in models_config

        # Cache the result
        _model_validation_cache[model_name] = exists
        return exists
    except Exception:
        # If we can't validate, assume it exists to avoid breaking things
        _model_validation_cache[model_name] = True
        return True


def clear_model_cache():
    """Clear the model validation cache. Call this when models.json changes."""
    global _model_validation_cache, _default_model_cache, _default_vision_model_cache
    _model_validation_cache.clear()
    _default_model_cache = None
    _default_vision_model_cache = None


def reset_session_model():
    """Reset the session-local model cache.

    This is primarily for testing purposes. In normal operation, the session
    model is set once at startup and only changes via set_model_name().
    """
    global _SESSION_MODEL
    _SESSION_MODEL = None


def model_supports_setting(model_name: str, setting: str) -> bool:
    """Check if a model supports a particular setting (e.g., 'temperature', 'seed').

    Args:
        model_name: The name of the model to check.
        setting: The setting name to check for (e.g., 'temperature', 'seed', 'top_p').

    Returns:
        True if the model supports the setting, False otherwise.
        Defaults to True for backwards compatibility if model config doesn't specify.
    """
    # GLM-4.7 and GLM-5 models always support clear_thinking setting
    if setting == "clear_thinking" and (
        "glm-4.7" in model_name.lower() or "glm-5" in model_name.lower()
    ):
        return True

    try:
        from code_muse.model_factory import ModelFactory

        models_config = ModelFactory.load_config()
        model_config = models_config.get(model_name, {})

        # Get supported_settings list, default to supporting common settings
        supported_settings = model_config.get("supported_settings")

        if supported_settings is None:
            # Default: assume common settings are supported for backwards compatibility
            # For Anthropic/Claude models, include extended thinking settings
            if model_name.startswith("claude-") or model_name.startswith("anthropic-"):
                base = ["temperature", "extended_thinking", "budget_tokens"]
                from code_muse.model_utils import supports_adaptive_thinking

                if supports_adaptive_thinking(model_name):
                    base.append("effort")
                return setting in base
            return setting in ["temperature", "seed"]

        return setting in supported_settings
    except Exception:
        # If we can't check, assume supported for safety
        return True


def get_global_model_name():
    """Return a valid model name for Muse to use.

    Uses session-local caching so that model changes in other terminals
    don't affect this running instance. The file is only read once at startup.

    1. If _SESSION_MODEL is set, return it (session cache)
    2. Otherwise, look at ``model`` in *muse.cfg*
    3. If that value exists **and** is present in *models.json*, use it
    4. Otherwise return the first model listed in *models.json*
    5. As a last resort fall back to ``claude-4-0-sonnet``

    The result is cached in _SESSION_MODEL for subsequent calls.
    """
    global _SESSION_MODEL

    # Return cached session model if already initialized
    if _SESSION_MODEL is not None:
        return _SESSION_MODEL

    # First access - initialize from file
    stored_model = _parser.get_value("model")

    if stored_model and _validate_model_exists(stored_model):
        _SESSION_MODEL = stored_model
        return _SESSION_MODEL

    # Either no stored model or it's not valid – choose default from models.json
    _SESSION_MODEL = _default_model_from_models_json()
    return _SESSION_MODEL


def set_model_name(model: str):
    """Sets the model name in both the session cache and persistent config file.

    Updates _SESSION_MODEL immediately for this process, and writes to the
    config file so new terminals will pick up this model as their default.
    """
    global _SESSION_MODEL

    # Update session cache immediately
    _SESSION_MODEL = model

    # Also persist to file for new terminal sessions
    from code_muse.config.parser import DEFAULT_SECTION

    config = configparser.ConfigParser()
    config.read(paths.CONFIG_FILE)
    if DEFAULT_SECTION not in config:
        config[DEFAULT_SECTION] = {}
    config[DEFAULT_SECTION]["model"] = model or ""
    with open(paths.CONFIG_FILE, "w", encoding="utf-8") as f:
        config.write(f)

    # Clear model cache when switching models to ensure fresh validation
    clear_model_cache()


def get_model_context_length() -> int:
    """
    Get the context length for the currently configured model from models.json
    """
    try:
        from code_muse.model_factory import ModelFactory

        model_configs = ModelFactory.load_config()
        model_name = get_global_model_name()

        # Get context length from model config
        model_config = model_configs.get(model_name, {})
        context_length = model_config.get("context_length", 128000)  # Default value

        return int(context_length)
    except Exception:
        # Fallback to default context length if anything goes wrong
        return 128000


def get_protected_token_count():
    """
    Returns the user-configured protected token count for message history compaction.
    This is the number of tokens in recent messages that won't be summarized.
    Defaults to 50000 if unset or misconfigured.
    Configurable by 'protected_token_count' key.
    Enforces that protected tokens don't exceed 75% of model context length.
    """
    val = _parser.get_value("protected_token_count")
    try:
        # Get the model context length to enforce the 75% limit
        model_context_length = get_model_context_length()
        max_protected_tokens = int(model_context_length * 0.75)

        # Parse the configured value
        configured_value = int(val) if val else 50000

        # Apply constraints: minimum 1000, maximum 75% of context length
        return max(1000, min(configured_value, max_protected_tokens))
    except (ValueError, TypeError):
        # If parsing fails, return a reasonable default that respects the 75% limit
        model_context_length = get_model_context_length()
        max_protected_tokens = int(model_context_length * 0.75)
        return min(50000, max_protected_tokens)
