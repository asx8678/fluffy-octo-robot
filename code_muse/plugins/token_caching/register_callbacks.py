"""Register token-caching callbacks and the /cache slash command."""

import logging

from code_muse.callbacks import register_callback
from code_muse.messaging import emit_info
from code_muse.plugins.token_caching.cache_hit_tracking import _session_stats
from code_muse.plugins.token_caching.stats_display import format_cache_stats

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Slash-command help
# ---------------------------------------------------------------------------


def _on_custom_command_help() -> list[tuple[str, str]]:
    """Provide help entry for /help display."""
    return [("cache", "Show token caching statistics")]


# ---------------------------------------------------------------------------
# Slash-command handler
# ---------------------------------------------------------------------------


async def _on_custom_command(command: str, name: str) -> bool | None:
    """Handle the /cache slash command.

    Usage:
        /cache

    Displays current session cache statistics.

    Returns:
        ``True`` if handled, ``None`` if the command name doesn't match.
    """
    if name != "cache":
        return None

    stats_text = format_cache_stats(_session_stats)
    emit_info(stats_text)
    return True


# ---------------------------------------------------------------------------
# Register callbacks
# ---------------------------------------------------------------------------

register_callback("custom_command_help", _on_custom_command_help)
register_callback("custom_command", _on_custom_command)

logger.debug("Token Caching plugin callbacks registered")
