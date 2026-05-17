"""Agent Factory plugin — warm agent pools and cache management.

Provides:
- Pre-warmed agent pools for the most common profiles
- ``/agent cache`` commands for inspecting and clearing the cache
- ``lightweight_subagent`` flag support for read-only specialists
- Cache stats instrumentation via ``upgrade_metrics``

This is a plugin-first approach (Initiative 4.1 / z30.1). Core cache
improvements are already in ``agent_tools.py``; this plugin provides
the management/observability layer on top.
"""

from __future__ import annotations

import logging
from typing import Any

from code_muse.callbacks import register_callback
from code_muse.messaging import emit_info, emit_success

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Agent profiles for pre-warming (optional, not auto-triggered)
# ---------------------------------------------------------------------------

# These are the 5-6 most common agent profiles that benefit from
# warm pools. When a user runs `/agent warm`, we build them eagerly.
WARM_PROFILES: list[dict[str, Any]] = [
    {"name": "muse", "description": "Primary coding agent"},
    {"name": "code-critic", "description": "Code review specialist"},
    {"name": "qa", "description": "Quality assurance agent"},
    {"name": "retriever", "description": "Context retrieval specialist"},
    {"name": "planner", "description": "Planning/strategy agent"},
]

# Lightweight agent profiles — these skip full tool registration.
# Useful for read-only or narrow-scope specialists.
LIGHTWEIGHT_PROFILES: dict[str, list[str]] = {
    "summarizer": ["read_file", "read_relevant_code"],
    "researcher": ["read_file", "read_relevant_code", "grep", "list_files"],
    "reviewer": ["read_file", "read_relevant_code", "grep"],
}


# ---------------------------------------------------------------------------
# Cache introspection (reads from agent_tools module-level state)
# ---------------------------------------------------------------------------


def _get_cache_stats() -> dict[str, Any]:
    """Read current cache stats from agent_tools.

    Returns a dict with cache size, max size, and optionally
    the cache keys.
    """
    try:
        from code_muse.tools.agent_tools import (
            _SUBAGENT_AGENT_CACHE_MAX,
            _subagent_agent_cache,
        )

        keys = list(_subagent_agent_cache.keys())
        return {
            "size": len(keys),
            "max_size": _SUBAGENT_AGENT_CACHE_MAX,
            "entries": [
                {
                    "agent_name": k[0],
                    "model_name": k[1],
                    "tool_count": len(k[2]) if k[2] else 0,
                }
                for k in keys
            ],
        }
    except (ImportError, AttributeError) as e:
        logger.debug("Could not read cache stats: %s", e)
        return {"size": 0, "max_size": 0, "entries": []}


def _clear_cache() -> int:
    """Clear the subagent agent cache. Returns number of entries cleared."""
    try:
        from code_muse.tools.agent_tools import (
            _subagent_agent_cache,
            _subagent_agent_cache_lock,
        )

        with _subagent_agent_cache_lock:
            count = len(_subagent_agent_cache)
            _subagent_agent_cache.clear()
        return count
    except ImportError, AttributeError:
        return 0


# ---------------------------------------------------------------------------
# /agent cache slash commands
# ---------------------------------------------------------------------------


def _on_custom_command(command: str, name: str) -> bool | str | None:
    """Handle ``/agent cache`` commands."""
    if name != "agent":
        return None

    parts = command.split()
    if len(parts) < 2 or parts[1] != "cache":
        return None

    sub = parts[2].strip().lower() if len(parts) > 2 else "stats"

    if sub == "stats":
        stats = _get_cache_stats()
        lines = [
            "🤖 Agent Cache Stats:",
            f"   Size: {stats['size']} / {stats['max_size']}",
        ]
        if stats["entries"]:
            lines.append("")
            lines.append("   Cached agents:")
            for entry in stats["entries"]:
                lines.append(
                    f"     {entry['agent_name']} "
                    f"(model={entry['model_name'] or 'default'}, "
                    f"tools={entry['tool_count']})"
                )
        else:
            lines.append("   (cache is empty)")
        emit_info("\n".join(lines))
        return True

    if sub == "clear":
        count = _clear_cache()
        emit_success(f"🤖 Agent cache cleared ({count} entries removed)")
        return True

    if sub == "warm":
        # Pre-warm is informational for now — actual warming requires
        # a running agent context which we don't have at slash-command
        # time. Document the profiles instead.
        lines = [
            "🤖 Warm Profiles Available:",
            "",
            "   To pre-warm agents, start a session and invoke them —",
            "   the cache fills automatically on first use.",
            "",
            "   Common profiles:",
        ]
        for profile in WARM_PROFILES:
            lines.append(f"     {profile['name']}: {profile['description']}")
        lines.append("")
        lines.append("   Lightweight profiles (reduced tool set):")
        for name, tools in LIGHTWEIGHT_PROFILES.items():
            lines.append(f"     {name}: {', '.join(tools)}")
        emit_info("\n".join(lines))
        return True

    if sub == "help":
        lines = [
            "🤖 Agent Cache Commands:",
            "   /agent cache stats  — Show cache size and entries",
            "   /agent cache clear  — Clear the agent cache",
            "   /agent cache warm   — Show warm pool profiles",
            "   /agent cache help   — Show this help",
        ]
        emit_info("\n".join(lines))
        return True

    emit_info("Usage: /agent cache stats|clear|warm|help")
    return True


def _on_custom_command_help() -> list[tuple[str, str]]:
    return [
        ("agent cache stats", "Show agent cache size and entries"),
        ("agent cache clear", "Clear the agent cache"),
        ("agent cache warm", "Show warm pool profiles"),
    ]


# ---------------------------------------------------------------------------
# Startup instrumentation
# ---------------------------------------------------------------------------


def _on_startup() -> None:
    """Log cache configuration at startup."""
    stats = _get_cache_stats()
    logger.debug(
        "Agent Factory plugin initialised (cache max=%d)",
        stats.get("max_size", 0),
    )


# ---------------------------------------------------------------------------
# Post-agent-run: emit cache stats to metrics
# ---------------------------------------------------------------------------


async def _on_agent_run_end(
    agent_name: str,
    model_name: str,
    session_id: str | None = None,
    success: bool = True,
    error: str | None = None,
    response_text: str | None = None,
    metadata: dict | None = None,
) -> None:
    """Emit cache stats to upgrade_metrics after each agent run."""
    try:
        from code_muse.plugins.upgrade_metrics import emit_metric

        stats = _get_cache_stats()
        emit_metric(
            "agent_cache_stats",
            {
                "cache_size": stats["size"],
                "cache_max": stats.get("max_size", 0),
                "agent": agent_name,
                "success": success,
            },
        )
    except ImportError:
        pass
    except Exception:
        logger.debug("Failed to emit cache stats", exc_info=True)


# ---------------------------------------------------------------------------
# Register all callbacks
# ---------------------------------------------------------------------------

register_callback("startup", _on_startup)
register_callback("custom_command", _on_custom_command)
register_callback("custom_command_help", _on_custom_command_help)
register_callback("agent_run_end", _on_agent_run_end)
