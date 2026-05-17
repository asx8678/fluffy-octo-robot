"""Configuration for the Context-Aware Code Reader plugin.

Provides a focused read tool that uses AST analysis to return only the
most relevant sections of a file instead of the entire contents.
"""

import logging

from code_muse.config.parser import get_value, set_config_value

logger = logging.getLogger(__name__)

# Config keys (prefixed to avoid collisions)
_KEY_ENABLED = "context_reader_enabled"
_KEY_MAX_RELEVANT_LINES = "context_reader_max_relevant_lines"
_KEY_AUTO_EXTENSIONS = "context_reader_auto_extensions"

_TRUTHY = ("true", "1", "yes", "on")

DEFAULT_EXTENSIONS = [
    ".py",
    ".js",
    ".ts",
    ".jsx",
    ".tsx",
    ".go",
    ".rs",
    ".java",
    ".rb",
    ".c",
    ".cpp",
    ".h",
    ".hpp",
]


def get_context_reader_enabled() -> bool:
    """Whether the context-aware reader tool is active. Default: True."""
    val = get_value(_KEY_ENABLED)
    if val is None:
        return True
    return str(val).strip().lower() in _TRUTHY


def set_context_reader_enabled(enabled: bool) -> None:
    """Enable or disable the context-aware reader."""
    set_config_value(_KEY_ENABLED, "true" if enabled else "false")
    logger.info("Context-aware reader %s", "enabled" if enabled else "disabled")


def get_max_relevant_lines() -> int:
    """Maximum number of lines to return in relevant mode (soft cap). Default: 200."""
    val = get_value(_KEY_MAX_RELEVANT_LINES)
    try:
        n = int(val) if val else 200
        return max(50, min(1000, n))
    except (ValueError, TypeError):
        return 200


def set_max_relevant_lines(n: int) -> None:
    clamped = max(50, min(1000, n))
    set_config_value(_KEY_MAX_RELEVANT_LINES, str(clamped))
    logger.info("Context reader max relevant lines set to %d", clamped)


def get_auto_extensions() -> list[str]:
    """File extensions the reader will attempt AST parsing on by default."""
    val = get_value(_KEY_AUTO_EXTENSIONS)
    if val:
        exts = [e.strip() for e in str(val).split(",") if e.strip()]
        return exts or DEFAULT_EXTENSIONS
    return DEFAULT_EXTENSIONS


def set_auto_extensions(exts: list[str]) -> None:
    set_config_value(_KEY_AUTO_EXTENSIONS, ",".join(exts))
    logger.info("Context reader auto extensions set to %s", exts)
