"""Config: XDG paths and file constants."""

import os
from pathlib import Path


def _get_xdg_dir(env_var: str, fallback: str) -> Path:
    """
    Get directory for code_muse files, defaulting to ~/.muse.

    XDG paths are only used when the corresponding environment variable
    is explicitly set by the user. Otherwise, we use the legacy ~/.muse
    directory for all file types (config, data, cache, state).

    Args:
        env_var: XDG environment variable name (e.g., "XDG_CONFIG_HOME")
        fallback: Fallback path relative to home (e.g., ".config")
                   - unused unless XDG var is set

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
