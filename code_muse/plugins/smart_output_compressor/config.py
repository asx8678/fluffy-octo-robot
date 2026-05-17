"""Configuration for smart_output_compressor."""

from __future__ import annotations

import logging

from code_muse.config.parser import get_value, set_config_value

logger = logging.getLogger(__name__)

_KEY_ENABLED = "smart_compressor_enabled"
_KEY_MAX_LINES = "smart_compressor_max_lines"

_TRUTHY = ("true", "1", "yes", "on")


def get_enabled() -> bool:
    """Whether the smart compressor is active. Default: True."""
    val = get_value(_KEY_ENABLED)
    if val is None:
        return True
    return str(val).strip().lower() in _TRUTHY


def set_enabled(val: bool) -> None:
    """Enable or disable the smart compressor."""
    set_config_value(_KEY_ENABLED, "true" if val else "false")
    logger.info("Smart compressor %s", "enabled" if val else "disabled")


def get_max_lines() -> int:
    """Maximum lines in the compressed output. Default: 200, clamped [50–2000]."""
    val = get_value(_KEY_MAX_LINES)
    try:
        n = int(val) if val else 200
        return max(50, min(2000, n))
    except ValueError, TypeError:
        return 200


def set_max_lines(n: int) -> None:
    clamped = max(50, min(2000, n))
    set_config_value(_KEY_MAX_LINES, str(clamped))
    logger.info("Smart compressor max lines set to %d", clamped)
