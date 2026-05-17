"""Register Critic Fabric plugin callbacks.

Minimal hook registration — just startup logging and a help entry for
the ``/critic-fabric`` status command.  The heavy lifting (preflight,
backend dispatch) is driven by import, not by hooks.
"""

from __future__ import annotations

import logging

from code_muse.callbacks import register_callback
from code_muse.messaging import emit_info

logger = logging.getLogger(__name__)


def _on_startup() -> None:
    """Log that Critic Fabric is loaded."""
    from code_muse.plugins.critic_fabric.backends import list_backends

    backends = list_backends()
    logger.debug(
        "Critic Fabric plugin loaded — backends: %s",
        ", ".join(backends) if backends else "(none)",
    )


async def _on_custom_command(command: str, name: str):
    """Handle /critic-fabric and /critic-fabric cache-stats commands."""
    if name != "critic-fabric":
        return None

    parts = command.strip().split()
    sub = parts[1] if len(parts) > 1 else "status"

    if sub == "cache-stats":
        from code_muse.plugins.critic_fabric.cache import get_review_cache

        cache = get_review_cache()
        s = cache.stats
        emit_info("🧵 Critic Fabric cache stats:")
        emit_info(f"   Entries: {s.size}")
        emit_info(f"   Hits:    {s.hits}")
        emit_info(f"   Misses:  {s.misses}")
        return True

    # Default: status
    from code_muse.plugins.critic_fabric.backends import list_backends
    from code_muse.plugins.critic_fabric.cache import get_review_cache

    backends = list_backends()
    cache = get_review_cache()
    s = cache.stats
    emit_info("🧵 Critic Fabric status:")
    emit_info(f"   Backends: {', '.join(backends) if backends else '(none)'}")
    emit_info("   Preflight: truncation_detector (enabled)")
    emit_info(f"   Cache: {s.size} entries, {s.hits} hits, {s.misses} misses")
    return True


def _on_custom_command_help():
    """Register help entries for /critic-fabric."""
    return [
        ("critic-fabric", "Show Critic Fabric backend status + cache stats"),
        ("critic-fabric cache-stats", "Show detailed cache hit/miss statistics"),
    ]


# ---------------------------------------------------------------------------
# Register all callbacks
# ---------------------------------------------------------------------------

register_callback("startup", _on_startup)
register_callback("custom_command", _on_custom_command)
register_callback("custom_command_help", _on_custom_command_help)

logger.debug("Critic Fabric plugin callbacks registered")
