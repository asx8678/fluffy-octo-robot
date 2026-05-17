"""Config: core parser, getters, setters, and simple config wrappers."""

import configparser
import threading
from contextlib import contextmanager
from pathlib import Path

import code_muse.config.paths as paths

DEFAULT_SECTION = "muse"
REQUIRED_KEYS = ["agent_name", "owner_name"]

# Config cache to avoid repeated file reads
_config_cache: tuple[str, float, configparser.ConfigParser | None] = None
_config_cache_lock = None  # Will be initialized lazily; FREE-THREADED: sync-only cache


def _get_cached_config() -> configparser.ConfigParser:
    """Return a cached ConfigParser, re-reading only when the file changes."""
    global _config_cache, _config_cache_lock

    if _config_cache_lock is None:
        _config_cache_lock = threading.Lock()

    cache_key = str(paths.CONFIG_FILE)
    try:
        mtime = paths.CONFIG_FILE.stat().st_mtime
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
        config.read(paths.CONFIG_FILE)
        _config_cache = (cache_key, mtime, config)
        return config


def ensure_config_exists():
    """
    Ensure that XDG directories and muse.cfg exist, prompting if needed.
    Returns configparser.ConfigParser for reading.
    """
    # Create all XDG directories with 0700 permissions per XDG spec
    for directory in [
        paths.CONFIG_DIR,
        paths.DATA_DIR,
        paths.CACHE_DIR,
        paths.STATE_DIR,
        paths.SKILLS_DIR,
    ]:
        if not directory.exists():
            directory.mkdir(parents=True, mode=0o700, exist_ok=True)
    # No need to re-import from paths; already imported as module
    exists = paths.CONFIG_FILE.is_file()
    config = configparser.ConfigParser()
    if exists:
        config.read(paths.CONFIG_FILE)
    missing = []
    if DEFAULT_SECTION not in config:
        config[DEFAULT_SECTION] = {}
    for key in REQUIRED_KEYS:
        if not config[DEFAULT_SECTION].get(key):
            missing.append(key)
    if missing:
        # Note: Using sys.stdout here for initial setup
        # before messaging system is available
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
        with open(paths.CONFIG_FILE, "w", encoding="utf-8") as f:
            config.write(f)
    return config


def get_value(key: str):
    config = _get_cached_config()
    val = config.get(DEFAULT_SECTION, key, fallback=None)
    return val


def get_config_keys():
    """
    Returns the list of all config keys currently in muse.cfg,
    plus certain preset expected keys.
    """
    from code_muse.config_appearance import DEFAULT_BANNER_COLORS

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
        "auto_approve",
    ]
    # Add pack agents control key
    default_keys.append("enable_pack_agents")
    # Add universal constructor control key
    default_keys.append("enable_universal_constructor")
    # Add hook retry limit keys
    default_keys.append("max_hook_retries")
    default_keys.append("max_critic_retries")
    # Add safety/cost control keys
    default_keys.append("max_consecutive_tool_errors")
    default_keys.append("overall_run_timeout")
    default_keys.append("total_tokens_limit")
    default_keys.append("max_tool_calls")
    # Add streaming control key
    default_keys.append("enable_streaming")
    # Add cancel agent key configuration
    default_keys.append("cancel_agent_key")
    # Add banner color keys
    for banner_name in DEFAULT_BANNER_COLORS:
        default_keys.append(f"banner_color_{banner_name}")
    # Add resume message count configuration
    default_keys.append("resume_message_count")
    # Add compaction tuning keys
    default_keys.append("recent_tool_results_to_keep")
    default_keys.append("max_messages_hard_cap")
    default_keys.append("filter_huge_message_threshold")

    config = configparser.ConfigParser()
    config.read(paths.CONFIG_FILE)
    keys = set(config[DEFAULT_SECTION].keys()) if DEFAULT_SECTION in config else set()
    keys.update(default_keys)
    return sorted(keys)


def set_config_value(key: str, value: str):
    """
    Sets a config value in the persistent config file.
    """
    global _config_cache
    config = configparser.ConfigParser()
    config.read(paths.CONFIG_FILE)
    if DEFAULT_SECTION not in config:
        config[DEFAULT_SECTION] = {}
    config[DEFAULT_SECTION][key] = value
    with open(paths.CONFIG_FILE, "w", encoding="utf-8") as f:
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
    config.read(paths.CONFIG_FILE)
    if DEFAULT_SECTION in config and key in config[DEFAULT_SECTION]:
        del config[DEFAULT_SECTION][key]
        with open(paths.CONFIG_FILE, "w", encoding="utf-8") as f:
            config.write(f)
    # Invalidate cache so subsequent reads pick up the change immediately
    _config_cache = None


@contextmanager
def isolated_config(temp_dir: Path):
    """Temporarily redirect ALL config paths to a temp directory. Restores on exit.

    Creates the full ``.muse/`` directory structure (config, data, cache, state
    subdirectories) under *temp_dir* and points every path constant in both
    ``code_muse.config.paths`` and ``code_muse.config`` to the temp equivalents.

    Unlike the previous implementation, this does **not** copy the real config
    file — each test starts from a clean slate.  This prevents cross-test bleed
    when a test mutates a shared config value.

    Yields ``(temp_config_file, temp_config_dir)``.
    """
    import code_muse.config as cfg_mod
    import code_muse.config.paths as paths

    global _config_cache

    # --- 1. Save originals ---------------------------------------------------
    _PATH_ATTRS = [
        # Base dirs
        "CONFIG_DIR",
        "DATA_DIR",
        "CACHE_DIR",
        "STATE_DIR",
        # Derived config files
        "CONFIG_FILE",
        # Data files
        "MODELS_FILE",
        "EXTRA_MODELS_FILE",
        "MODELS_CACHE_FILE",
        "AGENTS_DIR",
        "SKILLS_DIR",
        "CONTEXTS_DIR",
        # OAuth plugin model files
        "GEMINI_MODELS_FILE",
        "CHATGPT_MODELS_FILE",
        "CLAUDE_MODELS_FILE",
        "COPILOT_MODELS_FILE",
        # Cache files
        "AUTOSAVE_DIR",
        # State files
        "COMMAND_HISTORY_FILE",
    ]

    originals: dict[str, object] = {}
    for attr in _PATH_ATTRS:
        originals[attr] = getattr(paths, attr)

    # --- 2. Build temp directory structure -----------------------------------
    muse_root = temp_dir / ".muse"
    temp_config_dir = muse_root / "config"
    temp_data_dir = muse_root / "data"
    temp_cache_dir = muse_root / "cache"
    temp_state_dir = muse_root / "state"

    for d in (temp_config_dir, temp_data_dir, temp_cache_dir, temp_state_dir):
        d.mkdir(parents=True, exist_ok=True)

    temp_config_file = temp_config_dir / "muse.cfg"
    # Create an empty config so config readers don't crash
    temp_config_file.write_text("[muse]\n", encoding="utf-8")

    # --- 3. Compute temp values for all derived paths ------------------------
    temp_values: dict[str, object] = {
        "CONFIG_DIR": temp_config_dir,
        "DATA_DIR": temp_data_dir,
        "CACHE_DIR": temp_cache_dir,
        "STATE_DIR": temp_state_dir,
        "CONFIG_FILE": temp_config_file,
        "MODELS_FILE": temp_data_dir / "models.json",
        "EXTRA_MODELS_FILE": temp_data_dir / "extra_models.json",
        "MODELS_CACHE_FILE": temp_data_dir / "models_cache.json",
        "AGENTS_DIR": temp_data_dir / "agents",
        "SKILLS_DIR": temp_data_dir / "skills",
        "CONTEXTS_DIR": temp_data_dir / "contexts",
        "GEMINI_MODELS_FILE": temp_data_dir / "gemini_models.json",
        "CHATGPT_MODELS_FILE": temp_data_dir / "chatgpt_models.json",
        "CLAUDE_MODELS_FILE": temp_data_dir / "claude_models.json",
        "COPILOT_MODELS_FILE": temp_data_dir / "copilot_models.json",
        "AUTOSAVE_DIR": temp_cache_dir / "autosaves",
        "COMMAND_HISTORY_FILE": temp_state_dir / "command_history.txt",
    }

    # --- 4. Apply overrides in BOTH modules ----------------------------------
    for attr, val in temp_values.items():
        setattr(paths, attr, val)
        setattr(cfg_mod, attr, val)

    # --- 5. Clear caches -----------------------------------------------------
    from code_muse.config.models import clear_model_cache, reset_session_model

    clear_model_cache()
    reset_session_model()
    _config_cache = None

    try:
        yield temp_config_file, temp_config_dir
    finally:
        # --- 6. Restore originals --------------------------------------------
        for attr, val in originals.items():
            setattr(paths, attr, val)
            setattr(cfg_mod, attr, val)

        clear_model_cache()
        reset_session_model()
        _config_cache = None


# --- Simple getter/setter wrappers ---


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
    Allowed values: 'none', 'low', 'medium', 'high',
    'critical' (all case-insensitive for value).
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


def get_max_consecutive_tool_errors(default: int = 3) -> int:
    """Max consecutive tool errors before aborting the agent run."""
    val = get_value("max_consecutive_tool_errors")
    try:
        return int(val) if val else default
    except (ValueError, TypeError):
        return default


def get_total_tokens_limit(default: int = 0) -> int:
    """Return the maximum total tokens allowed for a single agent run.

    0 means no limit (unlimited).
    Configurable by 'total_tokens_limit' key.
    """
    val = get_value("total_tokens_limit")
    try:
        return int(val) if val else default
    except (ValueError, TypeError):
        return default


def get_max_tool_calls(default: int = 0) -> int:
    """Return the maximum number of tool calls allowed per agent run.

    0 means no limit (unlimited).
    Configurable by 'max_tool_calls' key.
    """
    val = get_value("max_tool_calls")
    try:
        return int(val) if val else default
    except (ValueError, TypeError):
        return default


def get_overall_run_timeout_seconds(default: int = 600) -> int:
    """Max wall-clock time in seconds for a single agent run (0 = no limit)."""
    val = get_value("overall_run_timeout")
    try:
        return int(val) if val else default
    except (ValueError, TypeError):
        return default


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
    except (ValueError, TypeError):
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
    except (ValueError, TypeError):
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
    return "summarization"


def get_message_limit(default: int = 1000) -> int:
    """Returns the user-configured message/request limit for the agent.

    Controls how many steps/requests the agent can take per run.
    Defaults to 1000 if unset or misconfigured.
    Configurable by 'message_limit' key.
    """
    val = get_value("message_limit")
    try:
        return int(val) if val else default
    except (ValueError, TypeError):
        return default


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


def get_allow_recursion() -> bool:
    """
    Get the allow_recursion configuration value.
    Returns True if recursion is allowed, False otherwise.
    """
    val = get_value("allow_recursion")
    if val is None:
        return True  # Default to True to allow recursion unless explicitly disabled
    return str(val).lower() in ("1", "true", "yes", "on")


def get_animations_enabled() -> bool:
    """Return whether terminal animations are enabled.

    Defaults to True if not configured.
    """
    val = get_value("animations_enabled")
    if val is None:
        return True
    return val.lower() in ("true", "1", "yes", "on")


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


def get_max_hook_retries() -> int:
    """Return the maximum number of plugin hook retries after an agent run.

    When a plugin hook returns ``{"retry": True, ...}`` the agent re-runs.
    This caps how many times that can happen for **non-critic** hooks to
    prevent runaway loops.  Critic-driven retries have a separate budget
    controlled by ``get_max_critic_retries()``.
    Defaults to 10.
    """
    val = get_value("max_hook_retries")
    if val is None:
        return 10
    try:
        n = int(val)
        return max(1, n)  # At least 1 to avoid nonsensical values
    except (ValueError, TypeError):
        return 10


def get_max_critic_retries() -> int:
    """Return the maximum number of critic-driven retries after an agent run.

    Critic retries (``{"retry": True, ..., "source": "critic"}``) are tracked
    separately from regular hook retries so the critic can have a larger
    iteration budget without starving other hooks.
    Defaults to 10.
    """
    val = get_value("max_critic_retries")
    if val is None:
        return 10
    try:
        n = int(val)
        return max(1, n)
    except (ValueError, TypeError):
        return 10


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


def get_agent_name():
    return get_value("agent_name") or "Muse"


def get_owner_name():
    return get_value("owner_name") or "Creator"


def get_puppy_name():
    return get_agent_name()


def get_filter_huge_message_threshold(default: int = 50000) -> int:
    """Return the max token threshold for filter_huge_messages.

    Configurable by 'filter_huge_message_threshold' key.
    Defaults to 50000 if unset or misconfigured.
    Clamped to a minimum of 1000.
    """
    val = get_value("filter_huge_message_threshold")
    try:
        threshold = int(val) if val else default
        return max(1000, threshold)
    except (ValueError, TypeError):
        return default


def get_recent_tool_results_to_keep(default: int = 7) -> int:
    """Return the number of recent tool results to keep in full during truncation.

    Configurable by 'recent_tool_results_to_keep' key.
    Older tool results get their content replaced with a truncation marker.
    Defaults to 7 if unset or misconfigured.
    Clamped to a minimum of 1.
    """
    val = get_value("recent_tool_results_to_keep")
    try:
        count = int(val) if val else default
        return max(1, count)
    except (ValueError, TypeError):
        return default


def get_max_messages_hard_cap(default: int = 50) -> int:
    """Return the max message count before forced compaction.

    Prevents unbounded history growth even when token proportion is
    below the compaction threshold. Short messages can accumulate
    past the token-based threshold without triggering compaction.
    Configurable by 'max_messages_hard_cap' key.
    Defaults to 50 if unset or misconfigured.
    Clamped to a minimum of 10.
    """
    val = get_value("max_messages_hard_cap")
    try:
        cap = int(val) if val else default
        return max(10, cap)
    except (ValueError, TypeError):
        return default
