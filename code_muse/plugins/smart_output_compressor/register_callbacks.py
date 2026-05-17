"""Callback registrations for smart_output_compressor.

Registers:
- The ``read_smart`` tool via ``register_tools`` callback
- System prompt guidance via ``load_prompt`` telling the model to prefer
  ``read_smart`` over ``read_file`` for structural reads
- ``/smart`` custom command for status/on/off

The built-in plugin loader imports this module; all ``register_callback``
calls execute at import time, so the plugin is activated automatically.
"""

from __future__ import annotations

import logging
from typing import Any

from code_muse.callbacks import register_callback
from code_muse.plugins.smart_output_compressor.config import get_enabled, set_enabled

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Callback implementations
# ---------------------------------------------------------------------------


def _register_smart_tool() -> list[dict[str, Any]]:
    """Return tool definitions for the central tool registry (or empty if disabled)."""
    if not get_enabled():
        return []
    from code_muse.plugins.smart_output_compressor.tools import register_tools

    return register_tools()


def _load_smart_compressor_prompt() -> str | None:
    """Inject guidance into the system prompt."""
    if not get_enabled():
        return None
    return (
        "\n\n## Smart Output Compressor\n"
        "A `read_smart` tool is available that compresses file output by:\n"
        "- Keeping all imports\n"
        "- Keeping function/class signatures\n"
        "- Eliding low-relevance function bodies\n"
        "- Focusing on areas matching your task's focus areas\n"
        "\n"
        "Prefer `read_smart` over `read_file` when you need to understand\n"
        "file structure without paying full token cost. Provide `focus_areas`\n"
        "derived from the current task for best results.\n"
    )


def _handle_smart_command(command: str, name: str) -> str | bool | None:
    """Handle /smart status|on|off commands."""
    if name != "smart":
        return None

    from code_muse.messaging import emit_info, emit_success

    tokens = command.strip().split(maxsplit=2)
    sub = tokens[1].strip().lower() if len(tokens) > 1 else "status"

    if sub == "status":
        from code_muse.plugins.smart_output_compressor.metrics import (
            format_metrics_summary,
        )

        status = "ON" if get_enabled() else "OFF"
        return f"Smart Compressor: {status}\n{format_metrics_summary()}"

    if sub == "on":
        set_enabled(True)
        emit_success("Smart compressor enabled")
        return True

    if sub == "off":
        set_enabled(False)
        emit_info("Smart compressor disabled")
        return True

    emit_info("Usage: /smart status|on|off")
    return True


def _custom_command_help() -> list[tuple[str, str]]:
    """Register /smart in the help menu."""
    return [
        ("smart status", "Show smart compressor status + compression metrics"),
        ("smart on|off", "Enable/disable smart compressor"),
    ]


def _on_startup() -> None:
    """Log plugin load at startup."""
    logger.info(
        "Smart output compressor loaded (%s)",
        "enabled" if get_enabled() else "disabled",
    )


# ---------------------------------------------------------------------------
# Module-scope registration (executed on import by the plugin loader)
# ---------------------------------------------------------------------------

register_callback("startup", _on_startup)
register_callback("register_tools", _register_smart_tool)
register_callback("load_prompt", _load_smart_compressor_prompt)
register_callback("custom_command", _handle_smart_command)
register_callback("custom_command_help", _custom_command_help)


# ---------------------------------------------------------------------------
# Backward-compat convenience function (not called by auto-loader)
# ---------------------------------------------------------------------------


def register_all_callbacks() -> None:
    """Manually activate the plugin.

    The built-in auto-loader already registers callbacks at import time
    (see module-scope calls above).  This function exists for callers
    that previously invoked it; it is a safe no-op because
    ``register_callback`` deduplicates by function identity.
    """
    register_callback("startup", _on_startup)
    register_callback("register_tools", _register_smart_tool)
    register_callback("load_prompt", _load_smart_compressor_prompt)
    register_callback("custom_command", _handle_smart_command)
    register_callback("custom_command_help", _custom_command_help)
    logger.info("Smart output compressor registered via register_all_callbacks()")
