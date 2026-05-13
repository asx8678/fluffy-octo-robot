"""Auto-generated tool definitions from Muse's TOOL_REGISTRY."""

from __future__ import annotations

from code_muse.plugins.tool_registry.registry import (
    ToolCategory,
    ToolMetadata,
    ToolTier,
)


def build_definitions() -> dict[str, ToolMetadata]:
    """Scan ``TOOL_REGISTRY`` and build ``ToolMetadata`` for each tool."""
    from code_muse.tools import TOOL_REGISTRY

    definitions: dict[str, ToolMetadata] = {}
    for name in TOOL_REGISTRY:
        read_only = _derive_read_only(name)
        definitions[name] = ToolMetadata(
            name=name,
            tier=_derive_tier(name),
            category=_derive_category(name),
            read_only=read_only,
            destructive=_derive_destructive(name),
            idempotent=_derive_idempotent(name, read_only),
            requires_confirmation=_derive_requires_confirmation(name),
            aliases=_derive_aliases(name),
        )
    return definitions


def _derive_tier(name: str) -> ToolTier:
    high = {
        "delete_file",
        "agent_run_shell_command",
        "universal_constructor",
        "mitmproxy",
        "chrome_cdp",
        "create_file",
    }
    if name in high or name.startswith("browser_"):
        return "high"
    low = {
        "list_files",
        "read_file",
        "grep",
        "list_agents",
        "list_or_search_skills",
        "agent_share_your_reasoning",
        "load_image_for_analysis",
    }
    if name in low:
        return "low"
    return "medium"


def _derive_category(name: str) -> ToolCategory:
    if name in ("list_files", "read_file", "grep"):
        return "search"
    if name in (
        "create_file",
        "replace_in_file",
        "delete_snippet",
        "delete_file",
        "edit_file",
    ):
        return "file_mods"
    if name.startswith("browser_"):
        return "browser"
    if name in ("chrome_cdp", "mitmproxy"):
        return "chrome_cdp"
    if name == "agent_run_shell_command":
        return "shell"
    if name in ("invoke_agent", "list_agents", "ask_user_question"):
        return "agent"
    if name in ("activate_skill", "list_or_search_skills"):
        return "skills"
    if name == "load_image_for_analysis":
        return "image"
    if name == "universal_constructor":
        return "constructor"
    if name in (
        "enter_plan_mode",
        "exit_plan_mode",
        "get_plan_mode",
        "approve_plan",
        "open_plan_in_editor",
    ):
        return "planning"
    return "utility"


def _derive_read_only(name: str) -> bool:
    return name.startswith(("get_", "list_", "search_", "find_", "read_"))


def _derive_destructive(name: str) -> bool:
    if name.startswith("delete_"):
        return True
    if name == "agent_run_shell_command":
        return True
    if name.startswith("browser_"):
        return True
    return name == "create_file"


def _derive_idempotent(name: str, read_only: bool) -> bool:
    if read_only:
        return True
    if name == "grep":
        return True
    if name.startswith("list_"):
        return True
    return bool(name.startswith("browser_find_"))


def _derive_requires_confirmation(name: str) -> bool:
    return name in ("universal_constructor", "agent_run_shell_command")


def _derive_aliases(name: str) -> list[str]:
    if name == "edit_file":
        return ["create_file", "replace_in_file", "delete_snippet"]
    return []


def _build_allow_lists() -> dict[str, list[str]]:
    definitions = build_definitions()
    return {
        "full_access": list(definitions.keys()),
        "read_only": [n for n, m in definitions.items() if m.read_only],
        "safe": [n for n, m in definitions.items() if not m.destructive],
        "file_operations": [
            "list_files",
            "read_file",
            "grep",
            "create_file",
            "replace_in_file",
            "delete_snippet",
            "delete_file",
        ],
        "browser": [n for n in definitions if n.startswith("browser_")],
        "shell": ["agent_run_shell_command", "mitmproxy"],
        "agent": ["invoke_agent", "list_agents", "ask_user_question"],
        "skills": [n for n, m in definitions.items() if m.category == "skills"],
        "search_only": ["list_files", "read_file", "grep"],
    }


ALLOW_LISTS: dict[str, list[str]] = _build_allow_lists()
