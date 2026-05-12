"""Config: model settings."""

import configparser

import code_muse.config as _config


def get_summarization_model_name() -> str:
    """Return the model used for compaction/summarization.

    Reads the ``summarization_model`` config key. If unset (or empty),
    falls back to :func:`get_global_model_name`, preserving legacy behavior
    for users who haven't explicitly configured a separate summarizer.

    Rationale: summarization is a different workload than main-agent chat —
    it's one-shot, large-context, and best served by a cheap-and-fast or
    long-context specialist model. Decoupling it from the global model lets
    users pick the right tool without changing their main agent.
    """
    value = _config.get_value("summarization_model")
    if value:
        return value
    return _config.get_global_model_name()


def set_summarization_model_name(model: str) -> None:
    """Persist the summarization model in the config file.

    Pass an empty string to clear the setting and fall back to the global
    model on subsequent calls to :func:`get_summarization_model_name`.
    """
    _config.set_config_value("summarization_model", model or "")


def get_muse_token():
    """Returns the muse_token from config, or None if not set."""
    return _config.get_value("muse_token")


def set_muse_token(token: str):
    """Sets the muse_token in the persistent config file."""
    _config.set_config_value("muse_token", token)


def get_openai_reasoning_effort() -> str:
    """Return the configured OpenAI reasoning effort (minimal, low, medium, high, xhigh)."""
    allowed_values = {"minimal", "low", "medium", "high", "xhigh"}
    configured = (
        (_config.get_value("openai_reasoning_effort") or "medium").strip().lower()
    )
    if configured not in allowed_values:
        return "medium"
    return configured


def set_openai_reasoning_effort(value: str) -> None:
    """Persist the OpenAI reasoning effort ensuring it remains within allowed values."""
    allowed_values = {"minimal", "low", "medium", "high", "xhigh"}
    normalized = (value or "").strip().lower()
    if normalized not in allowed_values:
        raise ValueError(
            f"Invalid reasoning effort '{value}'. Allowed: {', '.join(sorted(allowed_values))}"
        )
    _config.set_config_value("openai_reasoning_effort", normalized)


def get_openai_reasoning_summary() -> str:
    """Return the configured OpenAI reasoning summary mode.

    Supported values:
    - auto: let the provider decide the best summary style
    - concise: shorter reasoning summaries
    - detailed: fuller reasoning summaries
    """
    allowed_values = {"auto", "concise", "detailed"}
    configured = (
        (_config.get_value("openai_reasoning_summary") or "detailed").strip().lower()
    )
    if configured not in allowed_values:
        return "auto"
    return configured


def set_openai_reasoning_summary(value: str) -> None:
    """Persist the OpenAI reasoning summary mode ensuring it remains valid."""
    allowed_values = {"auto", "concise", "detailed"}
    normalized = (value or "").strip().lower()
    if normalized not in allowed_values:
        raise ValueError(
            f"Invalid reasoning summary '{value}'. Allowed: {', '.join(sorted(allowed_values))}"
        )
    _config.set_config_value("openai_reasoning_summary", normalized)


def get_openai_verbosity() -> str:
    """Return the configured OpenAI verbosity (low, medium, high).

    Controls how concise vs. verbose the model's responses are:
    - low: more concise responses
    - medium: balanced (default)
    - high: more verbose responses
    """
    allowed_values = {"low", "medium", "high"}
    configured = (_config.get_value("openai_verbosity") or "medium").strip().lower()
    if configured not in allowed_values:
        return "medium"
    return configured


def set_openai_verbosity(value: str) -> None:
    """Persist the OpenAI verbosity ensuring it remains within allowed values."""
    allowed_values = {"low", "medium", "high"}
    normalized = (value or "").strip().lower()
    if normalized not in allowed_values:
        raise ValueError(
            f"Invalid verbosity '{value}'. Allowed: {', '.join(sorted(allowed_values))}"
        )
    _config.set_config_value("openai_verbosity", normalized)


def get_temperature() -> float | None:
    """Return the configured model temperature (0.0 to 2.0).

    Returns:
        Float between 0.0 and 2.0 if set, None if not configured.
        This allows each model to use its own default when not overridden.
    """
    val = _config.get_value("temperature")
    if val is None or val.strip() == "":
        return None
    try:
        temp = float(val)
        # Clamp to valid range (most APIs accept 0-2)
        return max(0.0, min(2.0, temp))
    except ValueError, TypeError:
        return None


def set_temperature(value: float | None) -> None:
    """Set the global model temperature in config.

    Args:
        value: Temperature between 0.0 and 2.0, or None to clear.
               Lower values = more deterministic, higher = more creative.

    Note: Consider using set_model_setting() for per-model temperature.
    """
    if value is None:
        _config.set_config_value("temperature", "")
    else:
        # Validate and clamp
        temp = max(0.0, min(2.0, float(value)))
        _config.set_config_value("temperature", str(temp))


def _sanitize_model_name_for_key(model_name: str) -> str:
    """Sanitize model name for use in config keys.

    Replaces characters that might cause issues in config keys.
    """
    # Replace problematic characters with underscores
    sanitized = model_name.replace(".", "_").replace("-", "_").replace("/", "_")
    return sanitized.lower()


def get_model_setting(
    model_name: str, setting: str, default: float | None = None
) -> float | None:
    """Get a specific setting for a model.

    Args:
        model_name: The model name (e.g., 'gpt-5', 'wafer.ai-glm-5.1')
        setting: The setting name (e.g., 'temperature', 'top_p', 'seed')
        default: Default value if not set

    Returns:
        The setting value as a float, or default if not set.
    """
    sanitized_name = _config._sanitize_model_name_for_key(model_name)
    key = f"model_settings_{sanitized_name}_{setting}"
    val = _config.get_value(key)

    if val is None or val.strip() == "":
        return default

    try:
        return float(val)
    except ValueError, TypeError:
        return default


def set_model_setting(model_name: str, setting: str, value: float | None) -> None:
    """Set a specific setting for a model.

    Args:
        model_name: The model name (e.g., 'gpt-5', 'wafer.ai-glm-5.1')
        setting: The setting name (e.g., 'temperature', 'seed')
        value: The value to set, or None to clear
    """
    sanitized_name = _config._sanitize_model_name_for_key(model_name)
    key = f"model_settings_{sanitized_name}_{setting}"

    if value is None:
        _config.set_config_value(key, "")
    elif isinstance(value, float):
        # Round floats to nearest hundredth to avoid floating point weirdness
        # (allows 0.05 step increments for temperature/top_p)
        _config.set_config_value(key, str(round(value, 2)))
    else:
        _config.set_config_value(key, str(value))


def get_all_model_settings(model_name: str) -> dict:
    """Get all settings for a specific model.

    Args:
        model_name: The model name

    Returns:
        Dictionary of setting_name -> value for all configured settings.
    """

    sanitized_name = _config._sanitize_model_name_for_key(model_name)
    prefix = f"model_settings_{sanitized_name}_"

    config = configparser.ConfigParser()
    config.read(_config.CONFIG_FILE)

    settings = {}
    if _config.DEFAULT_SECTION in config:
        for key, val in config[_config.DEFAULT_SECTION].items():
            if key.startswith(prefix) and val.strip():
                setting_name = key[len(prefix) :]
                # Handle different value types
                val_stripped = val.strip()
                # Check for boolean values first
                if val_stripped.lower() in ("true", "false"):
                    settings[setting_name] = val_stripped.lower() == "true"
                else:
                    # Try to parse as number (int first, then float)
                    try:
                        # Try int first for cleaner values like budget_tokens
                        if "." not in val_stripped:
                            settings[setting_name] = int(val_stripped)
                        else:
                            settings[setting_name] = float(val_stripped)
                    except ValueError, TypeError:
                        # Keep as string if not a number
                        settings[setting_name] = val_stripped

    return settings


def clear_model_settings(model_name: str) -> None:
    """Clear all settings for a specific model.

    Args:
        model_name: The model name
    """

    sanitized_name = _config._sanitize_model_name_for_key(model_name)
    prefix = f"model_settings_{sanitized_name}_"

    config = configparser.ConfigParser()
    config.read(_config.CONFIG_FILE)

    if _config.DEFAULT_SECTION in config:
        keys_to_remove = [
            key for key in config[_config.DEFAULT_SECTION] if key.startswith(prefix)
        ]
        for key in keys_to_remove:
            del config[_config.DEFAULT_SECTION][key]

        with open(_config.CONFIG_FILE, "w", encoding="utf-8") as f:
            config.write(f)


def get_effective_model_settings(model_name: str | None = None) -> dict:
    """Get all effective settings for a model, filtered by what the model supports.

    This is the generalized way to get model settings. It:
    1. Gets all per-model settings from config
    2. Falls back to global temperature if not set per-model
    3. Filters to only include settings the model actually supports
    4. Converts seed to int (other settings stay as float)

    Args:
        model_name: The model name. If None, uses the current global model.

    Returns:
        Dictionary of setting_name -> value for all applicable settings.
        Ready to be unpacked into ModelSettings.
    """
    if model_name is None:
        model_name = _config.get_global_model_name()

    # Start with all per-model settings
    settings = _config.get_all_model_settings(model_name)

    # Fall back to global temperature if not set per-model
    if "temperature" not in settings:
        global_temp = _config.get_temperature()
        if global_temp is not None:
            settings["temperature"] = global_temp

    # Filter to only settings the model supports
    effective_settings = {}
    for setting_name, value in settings.items():
        if _config.model_supports_setting(model_name, setting_name):
            # Convert seed to int, keep others as float
            if setting_name == "seed" and value is not None:
                effective_settings[setting_name] = int(value)
            else:
                effective_settings[setting_name] = value

    return effective_settings


def get_effective_temperature(model_name: str | None = None) -> float | None:
    """Get the effective temperature for a model.

    Checks per-model settings first, then falls back to global temperature.

    Args:
        model_name: The model name. If None, uses the current global model.

    Returns:
        Temperature value, or None if not configured.
    """
    settings = _config.get_effective_model_settings(model_name)
    return settings.get("temperature")


def get_effective_top_p(model_name: str | None = None) -> float | None:
    """Get the effective top_p for a model.

    Args:
        model_name: The model name. If None, uses the current global model.

    Returns:
        top_p value, or None if not configured.
    """
    settings = _config.get_effective_model_settings(model_name)
    return settings.get("top_p")


def get_effective_seed(model_name: str | None = None) -> int | None:
    """Get the effective seed for a model.

    Args:
        model_name: The model name. If None, uses the current global model.

    Returns:
        seed value as int, or None if not configured.
    """
    settings = _config.get_effective_model_settings(model_name)
    return settings.get("seed")
