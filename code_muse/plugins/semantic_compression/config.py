"""Plugin-level config helpers for semantic_compression."""

import orjson as json
import logging

from code_muse.config import get_value, set_config_value

logger = logging.getLogger(__name__)

_CONFIG_KEY_ENABLED = "semantic_compression_enabled"
_CONFIG_KEY_ALLOWLIST = "semantic_compression_allowlist"
_CONFIG_KEY_BLOCKLIST = "semantic_compression_blocklist"
_TRUTHY = ("true", "1", "yes", "on")


def get_semantic_compression_enabled() -> bool:
    """Check if automatic semantic compression of tool output is enabled.

    Returns:
        True if enabled, False otherwise. Default: False (opt-in).
    """
    cfg_val = get_value(_CONFIG_KEY_ENABLED)
    if cfg_val is None:
        return False
    return str(cfg_val).strip().lower() in _TRUTHY


def set_semantic_compression_enabled(enabled: bool) -> None:
    """Enable or disable automatic semantic compression of tool output.

    Args:
        enabled: True to enable, False to disable.
    """
    set_config_value(_CONFIG_KEY_ENABLED, "true" if enabled else "false")
    logger.info("Semantic compression %s", "enabled" if enabled else "disabled")


def _parse_json_tool_list(config_value: str | None) -> set[str]:
    """Parse a JSON list of tool names from config.

    Returns:
        Set of tool names. Empty set if config is missing or invalid.
    """
    if not config_value:
        return set()
    try:
        parsed = orjson.loads(config_value)
        if isinstance(parsed, list):
            return {str(item).strip() for item in parsed if item}
    except json.JSONDecodeError as e:
        logger.error("Failed to parse tool list config: %s", e)
    return set()


def _serialize_tool_list(tool_names: set[str]) -> str:
    """Serialize a set of tool names to a JSON list string."""
    return orjson.dumps(sorted(tool_names))


def get_compression_allowlist() -> set[str]:
    """Get the set of tool names explicitly allowed for compression.

    Returns:
        Set of tool names. Compression is opt-in: only tools in this
        set will have their output compressed (when enabled).
        Empty means no tools are eligible for compression.
    """
    return _parse_json_tool_list(get_value(_CONFIG_KEY_ALLOWLIST))


def set_compression_allowlist(tool_names: set[str]) -> None:
    """Set the allowlist of tool names for compression.

    Args:
        tool_names: Set of tool names to allow. Empty set clears the allowlist.
    """
    set_config_value(_CONFIG_KEY_ALLOWLIST, _serialize_tool_list(tool_names))
    logger.info("Compression allowlist updated: %s", sorted(tool_names) or "(empty)")


def get_compression_blocklist() -> set[str]:
    """Get the set of tool names explicitly blocked from compression.

    Returns:
        Set of tool names that will never have their output compressed,
        even when compression is enabled.
    """
    return _parse_json_tool_list(get_value(_CONFIG_KEY_BLOCKLIST))


def set_compression_blocklist(tool_names: set[str]) -> None:
    """Set the blocklist of tool names for compression.

    Args:
        tool_names: Set of tool names to block. Empty set clears the blocklist.
    """
    set_config_value(_CONFIG_KEY_BLOCKLIST, _serialize_tool_list(tool_names))
    logger.info("Compression blocklist updated: %s", sorted(tool_names) or "(empty)")


def is_tool_allowed(tool_name: str) -> bool:
    """Check if a specific tool's output should be compressed.

    Logic (opt-in model — empty allowlist means NO tools eligible):
        1. If blocklist contains the tool name → False.
        2. If allowlist is empty → False (must explicitly opt-in tools).
        3. If allowlist is non-empty and does NOT contain the tool → False.
        4. Otherwise → True.

    Args:
        tool_name: Name of the tool to check.

    Returns:
        True if the tool's output may be compressed, False otherwise.
    """
    blocklist = get_compression_blocklist()
    if tool_name in blocklist:
        return False

    allowlist = get_compression_allowlist()
    if not allowlist:
        return False  # Opt-in: empty allowlist = no tools eligible
    return tool_name in allowlist
