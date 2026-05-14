"""Config: core parser, getters, setters, and simple config wrappers."""

import configparser
import shutil
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
    """Temporarily redirect config paths to a temp directory. Restores on exit."""
    import code_muse.config as cfg_mod
    import code_muse.config.paths as paths

    original_cfg = paths.CONFIG_FILE
    original_dir = paths.CONFIG_DIR
    temp_config_dir = temp_dir / ".muse"
    temp_config_dir.mkdir(parents=True, exist_ok=True)
    temp_config_file = temp_config_dir / "muse.cfg"
    if original_cfg.exists():
        shutil.copy(original_cfg, temp_config_file)
    # Override
    paths.CONFIG_FILE = temp_config_file
    cfg_mod.CONFIG_FILE = temp_config_file
    paths.CONFIG_DIR = temp_config_dir
    cfg_mod.CONFIG_DIR = temp_config_dir
    from code_muse.config.models import clear_model_cache

    clear_model_cache()
    try:
        yield temp_config_file, temp_config_dir
    finally:
        paths.CONFIG_FILE = original_cfg
        cfg_mod.CONFIG_FILE = original_cfg
        paths.CONFIG_DIR = original_dir
        cfg_mod.CONFIG_DIR = original_dir
        clear_model_cache()


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
    except ValueError, TypeError:
        return default


def get_overall_run_timeout_seconds(default: int = 600) -> int:
    """Max wall-clock time in seconds for a single agent run (0 = no limit)."""
    val = get_value("overall_run_timeout")
    try:
        return int(val) if val else default
    except ValueError, TypeError:
        return default


def get_total_tokens_limit(default: int = 0) -> int:
    """Max total tokens (input+output) for a single agent run (0 = no limit)."""
    val = get_value("total_tokens_limit")
    try:
        return int(val) if val else default
    except ValueError, TypeError:
        return default


def get_max_agent_steps(default: int = 15) -> int:
    """Max number of agent loop steps before truncation (0 = no limit)."""
    val = get_value("max_agent_steps")
    try:
        return int(val) if val else default
    except ValueError, TypeError:
        return default


def get_max_tool_calls(default: int = 0) -> int:
    """Max total tool calls for a single agent run (0 = no limit)."""
    val = get_value("max_tool_calls")
    try:
        return int(val) if val else default
    except ValueError, TypeError:
        return default


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
    except ValueError, TypeError:
        return default
