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
    """Handle /critic-fabric status command."""
    if name != "critic-fabric":
        return None

    from code_muse.plugins.critic_fabric.backends import list_backends

    backends = list_backends()
    emit_info("🧵 Critic Fabric status:")
    emit_info(f"   Backends: {', '.join(backends) if backends else '(none)'}")
    emit_info("   Preflight: truncation_detector (enabled)")
    return True


def _on_custom_command_help():
    """Register help entry for /critic-fabric."""
    return [
        ("critic-fabric", "Show Critic Fabric backend status"),
    ]


# ---------------------------------------------------------------------------
# Register all callbacks
# ---------------------------------------------------------------------------

register_callback("startup", _on_startup)
register_callback("custom_command", _on_custom_command)
register_callback("custom_command_help", _on_custom_command_help)

logger.debug("Critic Fabric plugin callbacks registered")
