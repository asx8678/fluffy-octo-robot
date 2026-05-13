"""Register token-caching callbacks and the /cache slash command."""

import logging

from code_muse.callbacks import register_callback
from code_muse.messaging import emit_info
from code_muse.plugins.token_caching.cache_hit_tracking import _session_stats
from code_muse.plugins.token_caching.stats_display import (
    format_cache_stats,
    format_cache_stats_short,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Agent lifecycle hooks
# ---------------------------------------------------------------------------


def _is_cache_capable_model(model_name: str | None) -> bool:
    """Return True if the model supports prompt caching."""
    if not model_name:
        return False
    name = model_name.lower()
    return (
        name.startswith("claude-") or name.startswith("anthropic-") or "bedrock" in name
    )


async def _on_agent_run_start(
    agent_name: str,
    model_name: str,
    session_id: str | None = None,
) -> None:
    """Log when a caching-capable model run begins."""
    if _is_cache_capable_model(model_name):
        logger.debug("Prompt caching active for %s (%s)", agent_name, model_name)


async def _on_agent_run_end(
    agent_name: str,
    model_name: str,
    session_id: str | None = None,
    success: bool = True,
    error: Exception | None = None,
    response_text: str | None = None,
    metadata: dict | None = None,
) -> None:
    """Surface cache stats at the end of an agent run."""
    stats = _session_stats
    short = format_cache_stats_short(stats)
    if short:
        logger.debug("Cache stats for %s: %s", agent_name or "agent", short)
        emit_info(short)


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

register_callback("agent_run_start", _on_agent_run_start)
register_callback("agent_run_end", _on_agent_run_end)
register_callback("custom_command_help", _on_custom_command_help)
register_callback("custom_command", _on_custom_command)

logger.debug("Token Caching plugin callbacks registered")
