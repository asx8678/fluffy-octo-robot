"""Configuration for the Blackboard plugin.

Manages runtime settings:
- Durable persistence on/off
- JSONL data file path
- Stats reset
"""

import logging
from pathlib import Path

from code_muse.config.paths import DATA_DIR

logger = logging.getLogger(__name__)

_BLACKBOARD_DIR = DATA_DIR / "blackboard"
_JSONL_FILENAME = "artifacts.jsonl"

# Module-level mutable state (in-process only)
_durable_enabled: bool = False


def is_durable_enabled() -> bool:
    """Return whether durable (JSONL) persistence is active."""
    return _durable_enabled


def set_durable_enabled(enabled: bool) -> None:
    """Toggle durable persistence on or off."""
    global _durable_enabled
    _durable_enabled = enabled
    logger.debug("Blackboard durable persistence: %s", "ON" if enabled else "OFF")


def get_durable_path() -> Path:
    """Return the path to the JSONL persistence file.

    Creates the parent directory if it doesn't exist.
    """
    _BLACKBOARD_DIR.mkdir(parents=True, exist_ok=True)
    return _BLACKBOARD_DIR / _JSONL_FILENAME
