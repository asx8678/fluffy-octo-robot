"""Register callbacks for the Tool Registry plugin."""

import logging

from rich.table import Table
from rich.text import Text

from code_muse.callbacks import register_callback
from code_muse.messaging import emit_info

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------
# Startup hook
# ------------------------------------------------------------------


def _on_startup() -> None:
    """Build registry on application startup."""
    try:
        from code_muse.plugins.tool_registry.definitions import build_definitions
        from code_muse.plugins.tool_registry.registry import get_registry

        registry = get_registry()
        for meta in build_definitions().values():
            registry.register(meta)
        logger.debug(
            "Tool Registry populated with %s tools",
            len(registry.all_primary_names()),
        )
    except Exception:
        logger.debug("Tool Registry startup failed", exc_info=True)


# ------------------------------------------------------------------
# Help entries
# ------------------------------------------------------------------


def _on_custom_command_help() -> list[tuple[str, str]]:
    """Provide help entries for /help display."""
    return [
        ("tools", "List all available tools with categories and tiers"),
    ]


# ------------------------------------------------------------------
# Slash-command handler
# ------------------------------------------------------------------


async def _on_custom_command(command: str, name: str) -> bool | None:
    """Handle ``/tools …`` slash commands.

    Returns ``True`` if handled, ``None`` if not a ``/tools`` command.
    """
    if name != "tools":
        return None

    tokens = command.strip().split()
    sub = tokens[1] if len(tokens) > 1 else "all"
    arg = tokens[2] if len(tokens) > 2 else None

    from code_muse.plugins.tool_registry.registry import (
        get_registry,
    )

    registry = get_registry()

    if sub == "category" and arg:
        # arg may be a valid ToolCategory literal
        try:
            metas = registry.get_by_category(arg)  # type: ignore[arg-type]
        except Exception:
            metas = []
    elif sub == "tier" and arg:
        tier = arg if arg in ("high", "medium", "low") else None
        if tier:
            metas = registry.get_by_tier(tier)  # type: ignore[arg-type]
        else:
            names = registry.all_primary_names()
            metas = [
                registry.get_metadata(n) for n in names if registry.get_metadata(n)
            ]
    elif sub == "destructive":
        metas = registry.get_destructive()
    elif sub == "read-only":
        metas = registry.get_read_only()
    else:
        names = registry.all_primary_names()
        metas = [registry.get_metadata(n) for n in names if registry.get_metadata(n)]

    table = Table(title=f"Tools ({len(metas)} total)")
    table.add_column("Name", style="cyan")
    table.add_column("Tier", style="yellow")
    table.add_column("Category", style="green")
    table.add_column("Safety", style="dim")

    for meta in sorted(metas, key=lambda m: m.name):
        safety: list[str] = []
        if meta.read_only:
            safety.append("📖")
        if meta.destructive:
            safety.append("⚠️")
        if meta.idempotent:
            safety.append("🔄")
        if meta.requires_confirmation:
            safety.append("🔒")
        table.add_row(
            meta.name,
            meta.tier,
            meta.category,
            Text(" ".join(safety) if safety else "—"),
        )

    emit_info(table)
    return True


# ------------------------------------------------------------------
# Register all callbacks
# ------------------------------------------------------------------

register_callback("startup", _on_startup)
register_callback("custom_command_help", _on_custom_command_help)
register_callback("custom_command", _on_custom_command)

logger.debug("Tool Registry plugin callbacks registered")
