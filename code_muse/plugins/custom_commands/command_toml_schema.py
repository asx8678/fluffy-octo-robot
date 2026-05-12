import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_KNOWN_FIELDS = {"prompt", "description"}


@dataclass
class CommandDef:
    """Definition of a custom command loaded from a TOML file."""

    name: str
    prompt: str
    description: str = ""


def _warn_unknown_fields(data: dict[str, Any], path: Path) -> None:
    unknown = set(data.keys()) - _KNOWN_FIELDS
    if unknown:
        logger.warning(
            "Unknown fields in command file %s: %s",
            path,
            ", ".join(sorted(unknown)),
        )


def parse_command_toml(path: Path) -> CommandDef:
    """Parse a single command definition from a TOML file.

    Args:
        path: Path to the ``.toml`` file.

    Returns:
        ``CommandDef`` with ``name`` derived from the file path,
        ``prompt`` from the TOML ``prompt`` key, and optional
        ``description``.

    Raises:
        ValueError: If ``prompt`` is missing, empty, or not a string.
    """
    import tomllib

    raw = path.read_text(encoding="utf-8")
    data = tomllib.loads(raw)

    if not isinstance(data, dict):
        raise ValueError(
            f"Invalid TOML in {path}: expected table, got {type(data).__name__}"
        )

    _warn_unknown_fields(data, path)

    prompt = data.get("prompt")
    if prompt is None:
        raise ValueError(f"Command file {path} is missing required field 'prompt'")
    if not isinstance(prompt, str):
        raise ValueError(
            f"Command file {path}: 'prompt' must be a string, got {type(prompt).__name__}"
        )
    if not prompt.strip():
        raise ValueError(f"Command file {path}: 'prompt' must be a non-empty string")

    description = data.get("description", "")
    if description is not None and not isinstance(description, str):
        raise ValueError(f"Command file {path}: 'description' must be a string")

    name = path.stem
    return CommandDef(name=name, prompt=prompt, description=description or "")
