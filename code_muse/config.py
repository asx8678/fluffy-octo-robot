import configparser
import contextlib
import datetime
import os
from pathlib import Path

from code_muse.session_storage import save_session


def _get_xdg_dir(env_var: str, fallback: str) -> Path:
    """
    Get directory for code_muse files, defaulting to ~/.muse.

    XDG paths are only used when the corresponding environment variable
    is explicitly set by the user. Otherwise, we use the legacy ~/.muse
    directory for all file types (config, data, cache, state).

    Args:
        env_var: XDG environment variable name (e.g., "XDG_CONFIG_HOME")
        fallback: Fallback path relative to home (e.g., ".config") - unused unless XDG var is set

    Returns:
        Path to the directory for code_muse files
    """
    # Use XDG directory ONLY if environment variable is explicitly set
    xdg_base = os.getenv(env_var)
    if xdg_base:
        return Path(xdg_base) / "muse"

    # Default to legacy ~/.muse for all file types
    return Path.home() / ".muse"


# XDG Base Directory paths
CONFIG_DIR = _get_xdg_dir("XDG_CONFIG_HOME", ".config")
DATA_DIR = _get_xdg_dir("XDG_DATA_HOME", ".local/share")
CACHE_DIR = _get_xdg_dir("XDG_CACHE_HOME", ".cache")
STATE_DIR = _get_xdg_dir("XDG_STATE_HOME", ".local/state")

# Configuration files (XDG_CONFIG_HOME)
CONFIG_FILE = CONFIG_DIR / "muse.cfg"

# Config cache to avoid repeated file reads
_config_cache: tuple[str, float, configparser.ConfigParser | None] = None
_config_cache_lock = None  # Will be initialized lazily; FREE-THREADED: sync-only cache


def _get_cached_config() -> configparser.ConfigParser:
    """Return a cached ConfigParser, re-reading only when the file changes."""
    global _config_cache, _config_cache_lock
    import threading

    if _config_cache_lock is None:
        _config_cache_lock = threading.Lock()

    cache_key = str(CONFIG_FILE)
    try:
        mtime = CONFIG_FILE.stat().st_mtime
    except OSError:
        mtime = 0.0

    with _config_cache_lock:
        if (
            _config_cache is not None
            and _config_cache[0] == cache_key
            and _config_cache[1] == mtime
        ):
            return _config_cache[2]
        # Cache miss or file changed — reload
        config = configparser.ConfigParser()
        config.read(CONFIG_FILE)
        _config_cache = (cache_key, mtime, config)
        return config


# Data files (XDG_DATA_HOME)
MODELS_FILE = DATA_DIR / "models.json"
EXTRA_MODELS_FILE = DATA_DIR / "extra_models.json"
MODELS_CACHE_FILE = DATA_DIR / "models_cache.json"
AGENTS_DIR = DATA_DIR / "agents"
SKILLS_DIR = DATA_DIR / "skills"
CONTEXTS_DIR = DATA_DIR / "contexts"

# OAuth plugin model files (XDG_DATA_HOME)
GEMINI_MODELS_FILE = DATA_DIR / "gemini_models.json"
CHATGPT_MODELS_FILE = DATA_DIR / "chatgpt_models.json"
CLAUDE_MODELS_FILE = DATA_DIR / "claude_models.json"
COPILOT_MODELS_FILE = DATA_DIR / "copilot_models.json"

# Cache files (XDG_CACHE_HOME)
AUTOSAVE_DIR = CACHE_DIR / "autosaves"

# State files (XDG_STATE_HOME)
COMMAND_HISTORY_FILE = STATE_DIR / "command_history.txt"


def get_subagent_verbose() -> bool:
    """Return True if sub-agent verbose output is enabled (default False).

    When False (default), sub-agents produce quiet, sparse output suitable
    for parallel execution. When True, sub-agents produce full verbose output
    like the main agent (useful for debugging).
    """
    cfg_val = get_value("subagent_verbose")
    if cfg_val is None:
        return False
    return str(cfg_val).strip().lower() in {"1", "true", "yes", "on"}


# Pack agents - the specialized sub-agents coordinated by Pack Leader

# Agents that require Universal Constructor to be enabled


def get_max_hook_retries() -> int:
    """Return the maximum number of plugin hook retries after an agent run.

    When a plugin hook returns ``{"retry": True, ...}`` the agent re-runs.
    This caps how many times that can happen to prevent runaway loops.
    Defaults to 3.
    """
    val = get_value("max_hook_retries")
    if val is None:
        return 3
    try:
        n = int(val)
        return max(1, n)  # At least 1 to avoid nonsensical values
    except ValueError, TypeError:
        return 3


def get_enable_streaming() -> bool:
    """
    Get the enable_streaming configuration value.
    Controls whether streaming (SSE) is used for model responses.
    Returns True if streaming is enabled, False otherwise.
    Defaults to True.
    """
    val = get_value("enable_streaming")
    if val is None:
        return True  # Default to True for better UX
    return str(val).lower() in ("1", "true", "yes", "on")


def get_auto_approve() -> bool:
    """
    Get the auto_approve configuration value.
    When True, all user approval prompts are automatically approved
    without showing the interactive menu.
    Defaults to True for a smoother UX.
    """
    val = get_value("auto_approve")
    if val is None:
        return True
    return str(val).lower() in ("1", "true", "yes", "on")


DEFAULT_SECTION = "muse"
REQUIRED_KEYS = ["agent_name", "owner_name"]

# Runtime-only autosave session ID (per-process)
_CURRENT_AUTOSAVE_ID: str | None = None

# Session-local model name (initialized from file on first access, then cached)
_SESSION_MODEL: str | None = None

# Cache containers for model validation and defaults
_model_validation_cache = {}
_default_model_cache = None
_default_vision_model_cache = None


def ensure_config_exists():
    """
    Ensure that XDG directories and muse.cfg exist, prompting if needed.
    Returns configparser.ConfigParser for reading.
    """
    # Create all XDG directories with 0700 permissions per XDG spec
    for directory in [CONFIG_DIR, DATA_DIR, CACHE_DIR, STATE_DIR, SKILLS_DIR]:
        if not directory.exists():
            directory.mkdir(parents=True, mode=0o700, exist_ok=True)
    exists = CONFIG_FILE.is_file()
    config = configparser.ConfigParser()
    if exists:
        config.read(CONFIG_FILE)
    missing = []
    if DEFAULT_SECTION not in config:
        config[DEFAULT_SECTION] = {}
    for key in REQUIRED_KEYS:
        if not config[DEFAULT_SECTION].get(key):
            missing.append(key)
    if missing:
        # Note: Using sys.stdout here for initial setup before messaging system is available
        import sys

        sys.stdout.write("[Run] Let's get your agent ready.\n")
        sys.stdout.flush()
        for key in missing:
            if key == "agent_name":
                val = input("What should we name the agent? ").strip()
            elif key == "owner_name":
                val = input("What's your name (so Muse knows its owner)? ").strip()
            else:
                val = input(f"Enter {key}: ").strip()
            config[DEFAULT_SECTION][key] = val

    # Set default values for important config keys if they don't exist
    if not config[DEFAULT_SECTION].get("auto_save_session"):
        config[DEFAULT_SECTION]["auto_save_session"] = "true"
    if not config[DEFAULT_SECTION].get("animations_enabled"):
        config[DEFAULT_SECTION]["animations_enabled"] = "true"

    # Write the config if we made any changes
    if missing or not exists:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            config.write(f)
    return config


def get_value(key: str):
    config = _get_cached_config()
    val = config.get(DEFAULT_SECTION, key, fallback=None)
    return val


def get_agent_name():
    return get_value("agent_name") or "Muse"


def get_puppy_name():
    return get_agent_name()


def get_owner_name():
    return get_value("owner_name") or "Creator"


def get_animations_enabled() -> bool:
    """Return whether terminal animations are enabled.

    Defaults to True if not configured.
    """
    val = get_value("animations_enabled")
    if val is None:
        return True
    return val.lower() in ("true", "1", "yes", "on")


# Legacy function removed - message history limit is no longer used
# Message history is now managed by token-based compaction system
# using get_protected_token_count() and get_summarization_threshold()


def get_allow_recursion() -> bool:
    """
    Get the allow_recursion configuration value.
    Returns True if recursion is allowed, False otherwise.
    """
    val = get_value("allow_recursion")
    if val is None:
        return True  # Default to True to allow recursion unless explicitly disabled
    return str(val).lower() in ("1", "true", "yes", "on")


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


# --- CONFIG SETTER STARTS HERE ---
def get_config_keys():
    """
    Returns the list of all config keys currently in muse.cfg,
    plus certain preset expected keys (e.g. "yolo_mode", "model", "compaction_strategy", "message_limit", "allow_recursion").
    """
    default_keys = [
        "yolo_mode",
        "model",
        "compaction_strategy",
        "protected_token_count",
        "compaction_threshold",
        "summarization_model",
        "message_limit",
        "allow_recursion",
        "openai_reasoning_effort",
        "openai_reasoning_summary",
        "openai_verbosity",
        "auto_save_session",
        "max_saved_sessions",
        "http2",
        "diff_context_lines",
        "default_agent",
        "temperature",
        "frontend_emitter_enabled",
        "frontend_emitter_max_recent_events",
        "frontend_emitter_queue_size",
        "auto_approve",
    ]
    # Add pack agents control key
    default_keys.append("enable_pack_agents")
    # Add universal constructor control key
    default_keys.append("enable_universal_constructor")
    # Add hook retry limit key
    default_keys.append("max_hook_retries")
    # Add streaming control key
    default_keys.append("enable_streaming")
    # Add cancel agent key configuration
    default_keys.append("cancel_agent_key")
    # Add banner color keys
    for banner_name in DEFAULT_BANNER_COLORS:
        default_keys.append(f"banner_color_{banner_name}")
    # Add resume message count configuration
    default_keys.append("resume_message_count")

    config = configparser.ConfigParser()
    config.read(CONFIG_FILE)
    keys = set(config[DEFAULT_SECTION].keys()) if DEFAULT_SECTION in config else set()
    keys.update(default_keys)
    return sorted(keys)


def set_config_value(key: str, value: str):
    """
    Sets a config value in the persistent config file.
    """
    global _config_cache
    config = configparser.ConfigParser()
    config.read(CONFIG_FILE)
    if DEFAULT_SECTION not in config:
        config[DEFAULT_SECTION] = {}
    config[DEFAULT_SECTION][key] = value
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        config.write(f)
    # Invalidate cache so subsequent reads pick up the change immediately
    _config_cache = None


# Alias for API compatibility
def set_value(key: str, value: str) -> None:
    """Set a config value. Alias for set_config_value."""
    set_config_value(key, value)


def reset_value(key: str) -> None:
    """Remove a key from the config file, resetting it to default."""
    global _config_cache
    config = configparser.ConfigParser()
    config.read(CONFIG_FILE)
    if DEFAULT_SECTION in config and key in config[DEFAULT_SECTION]:
        del config[DEFAULT_SECTION][key]
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            config.write(f)
    # Invalidate cache so subsequent reads pick up the change immediately
    _config_cache = None


# --- MODEL STICKY EXTENSION STARTS HERE ---


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
    stored_model = get_value("model")

    if stored_model:
        # Use cached validation to avoid hitting ModelFactory every time
        if _validate_model_exists(stored_model):
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
    config = configparser.ConfigParser()
    config.read(CONFIG_FILE)
    if DEFAULT_SECTION not in config:
        config[DEFAULT_SECTION] = {}
    config[DEFAULT_SECTION]["model"] = model or ""
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        config.write(f)

    # Clear model cache when switching models to ensure fresh validation
    clear_model_cache()


# --- PER-MODEL SETTINGS ---


# Legacy functions for backward compatibility


def normalize_command_history():
    """
    Normalize the command history file by converting old format timestamps to the new format.

    Old format example:
    - "# 2025-08-04 12:44:45.469829"

    New format example:
    - "# 2025-08-05T10:35:33" (ISO)
    """
    import os
    import re

    # Skip implementation during tests
    import sys

    if "pytest" in sys.modules:
        return

    # Skip normalization if file doesn't exist
    command_history_exists = COMMAND_HISTORY_FILE.is_file()
    if not command_history_exists:
        return

    try:
        # Read the entire file with encoding error handling for Windows
        with open(
            COMMAND_HISTORY_FILE, encoding="utf-8", errors="surrogateescape"
        ) as f:
            content = f.read()

        # Sanitize any surrogate characters that might have slipped in
        try:
            content = content.encode("utf-8", errors="surrogatepass").decode(
                "utf-8", errors="replace"
            )
        except UnicodeEncodeError, UnicodeDecodeError:
            pass  # Keep original if sanitization fails

        # Skip empty files
        if not content.strip():
            return

        # Define regex pattern for old timestamp format
        # Format: "# YYYY-MM-DD HH:MM:SS.ffffff"
        old_timestamp_pattern = r"# (\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}:\d{2})\.(\d+)"

        # Function to convert matched timestamp to ISO format
        def convert_to_iso(match):
            date = match.group(1)
            time = match.group(2)
            # Create ISO format (YYYY-MM-DDThh:mm:ss)
            return f"# {date}T{time}"

        # Replace all occurrences of the old timestamp format with the new ISO format
        updated_content = re.sub(old_timestamp_pattern, convert_to_iso, content)

        # Write the updated content back to the file only if changes were made
        if content != updated_content:
            import tempfile

            fd, tmp_path = tempfile.mkstemp(
                dir=str(COMMAND_HISTORY_FILE.parent), suffix=".tmp"
            )
            try:
                with os.fdopen(
                    fd, "w", encoding="utf-8", errors="surrogateescape"
                ) as f:
                    f.write(updated_content)
                os.replace(tmp_path, COMMAND_HISTORY_FILE)
            except BaseException:
                with contextlib.suppress(OSError):
                    os.unlink(tmp_path)
                raise
    except Exception as e:
        from code_muse.messaging import emit_error

        emit_error(
            f"An unexpected error occurred while normalizing command history: {str(e)}"
        )


def initialize_command_history_file():
    """Create the command history file if it doesn't exist.
    Handles migration from the old history file location for backward compatibility.
    Also normalizes the command history format if needed.
    """
    from pathlib import Path

    # Ensure the state directory exists before trying to create the history file
    if not STATE_DIR.exists():
        STATE_DIR.mkdir(parents=True, exist_ok=True)

    command_history_exists = COMMAND_HISTORY_FILE.is_file()
    if not command_history_exists:
        try:
            COMMAND_HISTORY_FILE.touch()

            # For backwards compatibility, copy the old history file, then remove it
            old_history_file = Path.home() / ".muse_history.txt"
            old_history_exists = old_history_file.is_file()
            if old_history_exists:
                import shutil

                shutil.copy2(old_history_file, COMMAND_HISTORY_FILE)
                old_history_file.unlink(missing_ok=True)

                # Normalize the command history format if needed
                normalize_command_history()
        except Exception as e:
            from code_muse.messaging import emit_error

            emit_error(
                f"An unexpected error occurred while trying to initialize history file: {str(e)}"
            )


def get_yolo_mode():
    """
    Checks muse.cfg for 'yolo_mode' (case-insensitive in value only).
    Defaults to False (safe mode) if not set.
    Allowed values for ON: 1, '1', 'true', 'yes', 'on' (all case-insensitive for value).
    """
    true_vals = {"1", "true", "yes", "on"}
    cfg_val = get_value("yolo_mode")
    if cfg_val is not None:
        return str(cfg_val).strip().lower() in true_vals
    return False


def get_safety_permission_level():
    """
    Checks muse.cfg for 'safety_permission_level' (case-insensitive in value only).
    Defaults to 'medium' if not set.
    Allowed values: 'none', 'low', 'medium', 'high', 'critical' (all case-insensitive for value).
    Returns the normalized lowercase string.
    """
    valid_levels = {"none", "low", "medium", "high", "critical"}
    cfg_val = get_value("safety_permission_level")
    if cfg_val is not None:
        normalized = str(cfg_val).strip().lower()
        if normalized in valid_levels:
            return normalized
    return "medium"  # Default to medium risk threshold


def get_grep_output_verbose():
    """
    Checks muse.cfg for 'grep_output_verbose' (case-insensitive in value only).
    Defaults to False (concise output) if not set.
    Allowed values for ON: 1, '1', 'true', 'yes', 'on' (all case-insensitive for value).

    When False (default): Shows only file names with match counts
    When True: Shows full output with line numbers and content
    """
    true_vals = {"1", "true", "yes", "on"}
    cfg_val = get_value("grep_output_verbose")
    if cfg_val is not None:
        return str(cfg_val).strip().lower() in true_vals
    return False


def get_protected_token_count():
    """
    Returns the user-configured protected token count for message history compaction.
    This is the number of tokens in recent messages that won't be summarized.
    Defaults to 50000 if unset or misconfigured.
    Configurable by 'protected_token_count' key.
    Enforces that protected tokens don't exceed 75% of model context length.
    """
    val = get_value("protected_token_count")
    try:
        # Get the model context length to enforce the 75% limit
        model_context_length = get_model_context_length()
        max_protected_tokens = int(model_context_length * 0.75)

        # Parse the configured value
        configured_value = int(val) if val else 50000

        # Apply constraints: minimum 1000, maximum 75% of context length
        return max(1000, min(configured_value, max_protected_tokens))
    except ValueError, TypeError:
        # If parsing fails, return a reasonable default that respects the 75% limit
        model_context_length = get_model_context_length()
        max_protected_tokens = int(model_context_length * 0.75)
        return min(50000, max_protected_tokens)


def get_resume_message_count() -> int:
    """
    Returns the number of messages to display when resuming a session.
    Defaults to 50 if unset or misconfigured.
    Configurable by 'resume_message_count' key via /set command.

    Example: /set resume_message_count=30
    """
    val = get_value("resume_message_count")
    try:
        configured_value = int(val) if val else 50
        # Enforce reasonable bounds: minimum 1, maximum 100
        return max(1, min(configured_value, 100))
    except ValueError, TypeError:
        return 50


def get_compaction_threshold():
    """
    Returns the user-configured compaction threshold as a float between 0.0 and 1.0.
    This is the proportion of model context that triggers compaction.
    Defaults to 0.85 (85%) if unset or misconfigured.
    Configurable by 'compaction_threshold' key.
    """
    val = get_value("compaction_threshold")
    try:
        threshold = float(val) if val else 0.85
        # Clamp between reasonable bounds
        return max(0.5, min(0.95, threshold))
    except ValueError, TypeError:
        return 0.85


def get_compaction_strategy() -> str:
    """
    Returns the user-configured compaction strategy.
    Options are 'summarization' or 'truncation'.
    Defaults to 'summarization' if not set or misconfigured.
    Configurable by 'compaction_strategy' key.
    """
    val = get_value("compaction_strategy")
    if val and val.lower() in ["summarization", "truncation"]:
        return val.lower()
    # Default to summarization
    return "truncation"


def get_http2() -> bool:
    """
    Get the http2 configuration value.
    Returns False if not set (default).
    """
    val = get_value("http2")
    if val is None:
        return False
    return str(val).lower() in ("1", "true", "yes", "on")


def set_http2(enabled: bool) -> None:
    """
    Sets the http2 configuration value.

    Args:
        enabled: Whether to enable HTTP/2 for httpx clients
    """
    set_config_value("http2", "true" if enabled else "false")


def get_message_limit(default: int = 1000) -> int:
    """
    Returns the user-configured message/request limit for the agent.
    This controls how many steps/requests the agent can take.
    Defaults to 1000 if unset or misconfigured.
    Configurable by 'message_limit' key.
    """
    val = get_value("message_limit")
    try:
        return int(val) if val else default
    except ValueError, TypeError:
        return default


def save_command_to_history(command: str):
    """Save a command to the history file with an ISO format timestamp.

    Args:
        command: The command to save
    """
    import datetime

    try:
        timestamp = datetime.datetime.now().isoformat(timespec="seconds")

        # Sanitize command to remove any invalid surrogate characters
        # that could cause encoding errors on Windows
        try:
            command = command.encode("utf-8", errors="surrogatepass").decode(
                "utf-8", errors="replace"
            )
        except UnicodeEncodeError, UnicodeDecodeError:
            # If that fails, do a more aggressive cleanup
            command = "".join(
                char if ord(char) < 0xD800 or ord(char) > 0xDFFF else "\ufffd"
                for char in command
            )

        with open(
            COMMAND_HISTORY_FILE, "a", encoding="utf-8", errors="surrogateescape"
        ) as f:
            f.write(f"\n# {timestamp}\n{command}\n")
    except Exception as e:
        from code_muse.messaging import emit_error

        emit_error(
            f"An unexpected error occurred while saving command history: {str(e)}"
        )


def get_auto_save_session() -> bool:
    """
    Checks muse.cfg for 'auto_save_session' (case-insensitive in value only).
    Defaults to True if not set.
    Allowed values for ON: 1, '1', 'true', 'yes', 'on' (all case-insensitive for value).
    """
    true_vals = {"1", "true", "yes", "on"}
    cfg_val = get_value("auto_save_session")
    if cfg_val is not None:
        return str(cfg_val).strip().lower() in true_vals
    return True


def set_auto_save_session(enabled: bool):
    """Sets the auto_save_session configuration value.

    Args:
        enabled: Whether to enable auto-saving of sessions
    """
    set_config_value("auto_save_session", "true" if enabled else "false")


def get_max_saved_sessions() -> int:
    """
    Gets the maximum number of sessions to keep.
    Defaults to 20 if not set.
    """
    cfg_val = get_value("max_saved_sessions")
    if cfg_val is not None:
        try:
            val = int(cfg_val)
            return max(0, val)  # Ensure non-negative
        except ValueError, TypeError:
            pass
    return 20


def set_max_saved_sessions(max_sessions: int):
    """Sets the max_saved_sessions configuration value.

    Args:
        max_sessions: Maximum number of sessions to keep (0 for unlimited)
    """
    set_config_value("max_saved_sessions", str(max_sessions))


# Defaults for diff highlight colors — single source of truth.


# =============================================================================
# Banner Color Configuration
# =============================================================================

# Default banner colors (Rich color names)
# A beautiful jewel-tone palette with semantic meaning:
#   - Blues/Teals: Reading & navigation (calm, informational)
#   - Warm tones: Actions & changes (edits, shell commands)
#   - Purples: AI thinking & reasoning (the "brain" colors)
#   - Greens: Completions & success
#   - Neutrals: Search & listings


def get_current_autosave_id() -> str:
    """Get or create the current autosave session ID for this process."""
    global _CURRENT_AUTOSAVE_ID
    if not _CURRENT_AUTOSAVE_ID:
        # Use a full timestamp so tests and UX can predict the name if needed
        _CURRENT_AUTOSAVE_ID = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    return _CURRENT_AUTOSAVE_ID


def rotate_autosave_id() -> str:
    """Force a new autosave session ID and return it."""
    global _CURRENT_AUTOSAVE_ID
    _CURRENT_AUTOSAVE_ID = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    return _CURRENT_AUTOSAVE_ID


def get_current_autosave_session_name() -> str:
    """Return the full session name used for autosaves (no file extension)."""
    return f"auto_session_{get_current_autosave_id()}"


def set_current_autosave_from_session_name(session_name: str) -> str:
    """Set the current autosave ID based on a full session name.

    Accepts names like 'auto_session_YYYYMMDD_HHMMSS' and extracts the ID part.
    Returns the ID that was set.
    """
    global _CURRENT_AUTOSAVE_ID
    prefix = "auto_session_"
    if session_name.startswith(prefix):
        _CURRENT_AUTOSAVE_ID = session_name[len(prefix) :]
    else:
        _CURRENT_AUTOSAVE_ID = session_name
    return _CURRENT_AUTOSAVE_ID


def auto_save_session_if_enabled() -> bool:
    """Automatically save the current session if auto_save_session is enabled."""
    if not get_auto_save_session():
        return False

    try:
        import pathlib

        from code_muse.agents.agent_manager import get_current_agent
        from code_muse.messaging import emit_info

        current_agent = get_current_agent()
        history = current_agent.get_message_history()
        if not history:
            return False

        now = datetime.datetime.now()
        session_name = get_current_autosave_session_name()
        autosave_dir = pathlib.Path(AUTOSAVE_DIR)

        metadata = save_session(
            history=history,
            session_name=session_name,
            base_dir=autosave_dir,
            timestamp=now.isoformat(),
            token_estimator=current_agent.estimate_tokens_for_message,
            auto_saved=True,
        )

        emit_info(
            f"[Done] Auto-saved session: {metadata.message_count} messages ({metadata.total_tokens} tokens)"
        )

        # Clean up old sessions after successful save
        try:
            from code_muse.session_storage import cleanup_sessions

            max_sessions = get_max_saved_sessions()
            if max_sessions > 0:
                removed = cleanup_sessions(autosave_dir, max_sessions)
                if removed:
                    emit_info(f"Cleaned up {len(removed)} old session(s)")
        except Exception:
            pass  # Non-critical; don't let cleanup failure affect the user

        return True

    except Exception as exc:  # pragma: no cover - defensive logging
        from code_muse.messaging import emit_error

        emit_error(f"Failed to auto-save session: {exc}")
        return False


def finalize_autosave_session() -> str:
    """Persist the current autosave snapshot and rotate to a fresh session."""
    auto_save_session_if_enabled()
    return rotate_autosave_id()


# API Key management functions


# --- FRONTEND EMITTER CONFIGURATION ---
def get_frontend_emitter_enabled() -> bool:
    """Check if frontend emitter is enabled."""
    val = get_value("frontend_emitter_enabled")
    if val is None:
        return True  # Enabled by default
    return str(val).lower() in ("1", "true", "yes", "on")


def get_frontend_emitter_max_recent_events() -> int:
    """Get max number of recent events to buffer."""
    val = get_value("frontend_emitter_max_recent_events")
    if val is None:
        return 100
    try:
        return int(val)
    except ValueError:
        return 100


def get_frontend_emitter_queue_size() -> int:
    """Get max subscriber queue size."""
    val = get_value("frontend_emitter_queue_size")
    if val is None:
        return 100
    try:
        return int(val)
    except ValueError:
        return 100


# Re-exports from config submodules (kept at bottom to avoid circular imports)
from code_muse.config_agent import (  # noqa: E402,F401
    PACK_AGENT_NAMES,
    UC_AGENT_NAMES,
    clear_agent_pinned_model,
    get_agent_pinned_model,
    get_agents_pinned_to_model,
    get_all_agent_pinned_models,
    get_default_agent,
    get_pack_agents_enabled,
    get_project_agents_directory,
    get_universal_constructor_enabled,
    get_user_agents_directory,
    set_agent_pinned_model,
    set_default_agent,
    set_universal_constructor_enabled,
)
from code_muse.config_appearance import (  # noqa: E402,F401
    _DEFAULT_DIFF_ADDITION_HEX,
    _DEFAULT_DIFF_DELETION_HEX,
    DEFAULT_BANNER_COLORS,
    _coerce_to_hex,
    get_all_banner_colors,
    get_banner_color,
    get_diff_addition_color,
    get_diff_context_lines,
    get_diff_deletion_color,
    get_suppress_informational_messages,
    get_suppress_thinking_messages,
    reset_all_banner_colors,
    reset_banner_color,
    set_banner_color,
    set_diff_addition_color,
    set_diff_deletion_color,
    set_diff_highlight_style,
    set_suppress_informational_messages,
    set_suppress_thinking_messages,
)
from code_muse.config_model import (  # noqa: E402,F401
    _sanitize_model_name_for_key,
    clear_model_settings,
    get_all_model_settings,
    get_effective_model_settings,
    get_effective_seed,
    get_effective_temperature,
    get_effective_top_p,
    get_model_setting,
    get_muse_token,
    get_openai_reasoning_effort,
    get_openai_reasoning_summary,
    get_openai_verbosity,
    get_summarization_model_name,
    get_temperature,
    set_model_setting,
    set_muse_token,
    set_openai_reasoning_effort,
    set_openai_reasoning_summary,
    set_openai_verbosity,
    set_summarization_model_name,
    set_temperature,
)
from code_muse.config_security import (  # noqa: E402,F401
    get_api_key,
    load_api_keys_to_environment,
    set_api_key,
)
