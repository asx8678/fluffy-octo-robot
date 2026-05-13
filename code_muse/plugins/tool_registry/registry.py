"""Core registry for tool metadata."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

ToolTier = Literal["high", "medium", "low"]
ToolCategory = Literal[
    "search",
    "file_ops",
    "file_mods",
    "browser",
    "chrome_cdp",
    "web",
    "shell",
    "mitmproxy",
    "agent",
    "skills",
    "image",
    "planning",
    "constructor",
    "integration",
    "utility",
]


@dataclass
class ToolMetadata:
    """Metadata describing a Muse tool for categorisation, tiering and safety policy."""

    name: str
    tier: ToolTier
    category: ToolCategory
    read_only: bool = False
    destructive: bool = False
    idempotent: bool = False
    requires_confirmation: bool = False
    aliases: list[str] = field(default_factory=list)
    description: str = ""


class ToolRegistry:
    """In-memory registry of tool metadata."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolMetadata] = {}
        self._aliases: dict[str, str] = {}

    def register(self, metadata: ToolMetadata) -> None:
        """Register a tool and its aliases."""
        self._tools[metadata.name] = metadata
        for alias in metadata.aliases:
            self._aliases[alias] = metadata.name

    def get_metadata(self, name: str) -> ToolMetadata | None:
        """Look up metadata by primary name or alias."""
        if name in self._tools:
            return self._tools[name]
        primary = self._aliases.get(name)
        return self._tools.get(primary) if primary else None

    def all_primary_names(self) -> list[str]:
        """Return all registered primary tool names."""
        return sorted(self._tools.keys())

    def get_by_category(self, category: ToolCategory) -> list[ToolMetadata]:
        """Return all tools in a given category."""
        return [m for m in self._tools.values() if m.category == category]

    def get_by_tier(self, tier: ToolTier) -> list[ToolMetadata]:
        """Return all tools with a given tier."""
        return [m for m in self._tools.values() if m.tier == tier]

    def get_destructive(self) -> list[ToolMetadata]:
        """Return all tools flagged as destructive."""
        return [m for m in self._tools.values() if m.destructive]

    def get_read_only(self) -> list[ToolMetadata]:
        """Return all tools flagged as read-only."""
        return [m for m in self._tools.values() if m.read_only]

    def resolve_allow_list(self, names: list[str]) -> list[str]:
        """Deduplicate, resolve aliases and filter out unknown names."""
        resolved: set[str] = set()
        for name in names:
            meta = self.get_metadata(name)
            if meta is not None:
                resolved.add(meta.name)
        return sorted(resolved)


_TOOL_REGISTRY_INSTANCE: ToolRegistry | None = None


def get_registry() -> ToolRegistry:
    """Return the singleton ``ToolRegistry`` instance."""
    global _TOOL_REGISTRY_INSTANCE
    if _TOOL_REGISTRY_INSTANCE is None:
        _TOOL_REGISTRY_INSTANCE = ToolRegistry()
    return _TOOL_REGISTRY_INSTANCE


def derive_annotations(name: str) -> dict[str, bool]:
    """Derive safety annotations from tool naming conventions.

    Tools starting with ``get_``, ``list_``, ``search_``, ``find_`` or
    ``read_`` are considered read-only and idempotent.  Tools starting
    with ``delete_`` are considered destructive.
    """
    result: dict[str, bool] = {}
    if name.startswith(("get_", "list_", "search_", "find_", "read_")):
        result["read_only"] = True
        result["idempotent"] = True
    if name.startswith("delete_"):
        result["destructive"] = True
    return result
