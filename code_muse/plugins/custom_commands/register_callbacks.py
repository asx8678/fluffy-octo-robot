import logging
from typing import Any

from code_muse.callbacks import register_callback
from code_muse.messaging import emit_info, emit_success
from code_muse.plugins.custom_commands.args_injection import (
    apply_shell_flags,
    detect_shell_blocks,
    inject_args,
)
from code_muse.plugins.custom_commands.command_discovery import (
    CommandDef,
    discover_commands,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Result wrapper so command_handler.py sends the prompt to the agent
# ---------------------------------------------------------------------------


class CustomCommandResult:
    """Marker class for custom-command results that should be processed as input."""

    def __init__(self, content: str):
        self.content = content

    def __str__(self) -> str:
        return self.content

    def __repr__(self) -> str:
        return f"CustomCommandResult({len(self.content)} chars)"


# ---------------------------------------------------------------------------
# Command cache
# ---------------------------------------------------------------------------

_command_cache: dict[str, CommandDef] = {}
_cache_loaded: bool = False


def _load_commands() -> None:
    """Load or reload the command discovery cache."""
    global _command_cache, _cache_loaded
    _command_cache = discover_commands()
    _cache_loaded = True
    logger.debug("Loaded %d custom command(s)", len(_command_cache))


def _reload_commands() -> None:
    """Clear cache and re-discover commands."""
    global _command_cache, _cache_loaded
    _command_cache.clear()
    _cache_loaded = False
    _load_commands()


# ---------------------------------------------------------------------------
# Callbacks
# ---------------------------------------------------------------------------


def _on_custom_command(command: str, name: str) -> Any:
    """Handle a TOML-defined custom command.

    Args:
        command: Full command string (e.g. ``"/git:fix arg1"``).
        name: Command name extracted by the handler (e.g. ``"git:fix"``).

    Returns:
        - ``CustomCommandResult(prompt)`` when a custom command is resolved
          and should be sent to the agent as input.
        - ``True`` for management commands (``/commands list``, ``/commands reload``).
        - ``None`` if the command is not recognised (passthrough).
    """
    if not name:
        return None

    # Management commands
    if name == "commands":
        return _handle_commands_management(command)

    # Ensure cache is populated
    if not _cache_loaded:
        _load_commands()

    cmd_def = _command_cache.get("/" + name)
    if cmd_def is None:
        return None

    # Extract args (everything after the command name)
    parts = command.split(maxsplit=1)
    args = parts[1] if len(parts) > 1 else ""

    # Inject {{args}}
    prompt = inject_args(cmd_def.prompt, args)

    # Shell-context mode: auto-append efficiency flags
    if detect_shell_blocks(prompt):
        prompt = apply_shell_flags(prompt)

    return CustomCommandResult(prompt)


def _handle_commands_management(command: str) -> bool:
    """Handle ``/commands``, ``/commands list``, and ``/commands reload``."""
    rest = command.split(maxsplit=1)
    subcommand = rest[1].strip().lower() if len(rest) > 1 else ""

    if subcommand == "reload":
        _reload_commands()
        emit_success(f"🔄 Reloaded {len(_command_cache)} custom command(s)")
        return True

    # Default to list
    return _commands_list()


def _commands_list() -> bool:
    """Display all discovered custom commands and return ``True``."""
    if not _cache_loaded:
        _load_commands()

    if not _command_cache:
        emit_info("No custom commands found.")
        emit_info(
            "Create .toml files in ~/.muse/commands/ or .muse/commands/"
        )
        return True

    lines: list[str] = ["Custom commands:"]
    for namespace in sorted(_command_cache):
        cmd = _command_cache[namespace]
        desc = f" — {cmd.description}" if cmd.description else ""
        lines.append(f"  {namespace}{desc}")

    lines.append("")
    lines.append("Management:")
    lines.append("  /commands list   — Show this list")
    lines.append("  /commands reload — Rescan command directories")

    emit_info("\n".join(lines))
    return True


def _on_custom_command_help() -> list[tuple[str, str]]:
    """Return help entries for all discovered commands."""
    if not _cache_loaded:
        _load_commands()

    entries: list[tuple[str, str]] = []
    for namespace in sorted(_command_cache):
        cmd = _command_cache[namespace]
        desc = cmd.description or "Custom TOML command"
        entries.append((namespace.lstrip("/"), desc))

    # Management commands
    entries.append(("commands list", "List available custom commands"))
    entries.append(("commands reload", "Rescan custom command directories"))
    return entries


def _on_startup() -> None:
    """Load commands at startup so they're available immediately."""
    _load_commands()


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

register_callback("custom_command", _on_custom_command)
register_callback("custom_command_help", _on_custom_command_help)
register_callback("startup", _on_startup)
