import logging
import re
from pathlib import Path

from code_muse.plugins.custom_commands.command_toml_schema import (
    CommandDef,
    parse_command_toml,
)

logger = logging.getLogger(__name__)

_VALID_NAME_RE = re.compile(r"^[a-zA-Z0-9_-]+$")

_USER_COMMANDS_DIR = Path.home() / ".muse" / "commands"
_PROJECT_COMMANDS_DIR = Path(".muse") / "commands"


def _resolve_namespace(file_path: Path, commands_dir: Path) -> str:
    """Derive the command namespace from its path relative to *commands_dir*.

    Examples:
        - ``commands_dir / "fix.toml"`` → ``/fix``
        - ``commands_dir / "git" / "fix.toml"`` → ``/git:fix``
    """
    rel = file_path.relative_to(commands_dir)
    # Drop the .toml extension and replace path separators with colons
    namespace = "/" + str(rel.with_suffix("")).replace("/", ":")
    return namespace


def _scan_tier(commands_dir: Path, tier_label: str) -> dict[str, CommandDef]:
    """Scan a single directory tier for ``*.toml`` command files.

    Returns a mapping of ``namespace → CommandDef``.
    """
    discovered: dict[str, CommandDef] = {}
    if not commands_dir.exists():
        return discovered

    # Collect both flat and nested files
    files = sorted(commands_dir.rglob("*.toml"))
    for file_path in files:
        # Skip hidden files / directories
        if any(
            part.startswith(".") for part in file_path.relative_to(commands_dir).parts
        ):
            continue

        name_part = file_path.stem
        if not _VALID_NAME_RE.match(name_part):
            logger.warning(
                "Skipping invalid command filename %s (names must be alphanumeric, hyphens, underscores)",
                file_path,
            )
            continue

        namespace = _resolve_namespace(file_path, commands_dir)
        try:
            cmd_def = parse_command_toml(file_path)
            cmd_def.name = namespace  # override with the namespaced name
        except ValueError as exc:
            logger.warning("Failed to load command from %s: %s", file_path, exc)
            continue

        discovered[namespace] = cmd_def

    return discovered


def discover_commands(
    user_dir: Path | None = None,
    project_dir: Path | None = None,
) -> dict[str, CommandDef]:
    """Discover custom commands from user and project tiers.

    Scans ``~/.muse/commands/**/*.toml`` (user tier) and
    ``.muse/commands/**/*.toml`` (project tier).  Project
    definitions override user definitions for the same namespace.

    Returns:
        Mapping of ``namespace → CommandDef``.
    """
    user_tier = _scan_tier(user_dir or _USER_COMMANDS_DIR, "user")
    project_tier = _scan_tier(project_dir or _PROJECT_COMMANDS_DIR, "project")

    # Project tier overrides user tier
    merged = dict(user_tier)
    merged.update(project_tier)
    return merged
