"""Plugin registration for the Context-Aware Code Reader.

Registers:
- The ``read_relevant_code`` tool via ``register_tools`` callback
- System prompt guidance via ``load_prompt`` telling the model to prefer
  ``read_relevant_code`` over ``read_file`` for source-code reads
- ``/read-relevant`` custom command for manual use

The built-in plugin loader imports this module; all ``register_callback``
calls execute at import time, so the plugin is activated automatically.
"""

from __future__ import annotations

import logging
from typing import Any

from code_muse.callbacks import register_callback
from code_muse.messaging import emit_info
from code_muse.plugins.context_aware_reader.config import (
    get_context_reader_enabled,
)
from code_muse.plugins.context_aware_reader.focus import extract_focus_areas
from code_muse.plugins.context_aware_reader.reader import read_relevant_code
from code_muse.tools.file_operations import ReadFileOutput

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Callback implementations
# ---------------------------------------------------------------------------


def _register_read_relevant_tool() -> list[dict[str, Any]]:
    """Return tool definitions for the central tool registry.

    ``on_register_tools()`` expects each callback to return a list of
    dicts with ``{"name": str, "register_func": callable}`` where
    *register_func(agent)* registers a pydantic-ai tool via ``@agent.tool``.
    """

    def _read_relevant_code_tool(
        context: Any,
        file_path: str,
        focus_areas: list[str] | None = None,
        task_description: str | None = None,
    ) -> ReadFileOutput:
        """Read only the most relevant sections of a source file for the current task.

        Use this INSTEAD of read_file when you only need specific functions,
        classes, or areas related to the current task. Dramatically more
        token-efficient than reading the whole file.

        Provide focus_areas (e.g. ["process_data", "UserService"]) when you
        know what symbols you need. If focus_areas is omitted but you supply
        a task_description, focus areas will be derived automatically from
        the task text. Call without focus_areas or task_description only
        for initial structure discovery of an unfamiliar file.
        """
        # Auto-derive focus areas from task text when not supplied
        if not focus_areas and task_description:
            focus_areas = extract_focus_areas(task_description)

        return read_relevant_code(file_path, focus_areas=focus_areas)

    def _register_func(agent: Any) -> None:
        """Register the tool with a pydantic-ai agent via @agent.tool."""
        agent.tool(_read_relevant_code_tool)

    return [{"name": "read_relevant_code", "register_func": _register_func}]


def _register_read_relevant_tool_disabled() -> list[dict[str, Any]]:
    """No-op variant used when the plugin is disabled."""
    return []


def _load_context_reader_prompt() -> str | None:
    """Inject guidance into the system prompt."""
    return (
        "\n\n## Context-Aware Code Reader — DEFAULT READ PATH\n"
        "When reading source-code files, **prefer "
        "`read_relevant_code` over `read_file` by default.**\n"
        "\n"
        "### When to use `read_relevant_code`\n"
        "- For ANY source-code file read where you don't need "
        "the exact full contents.\n"
        "- Provide `focus_areas` derived from the current task: "
        "function names, class names, symbol identifiers, "
        "dotted paths, error names, test names, config keys, "
        "endpoint names, or any symbol in the task description.\n"
        "- If you don't know specific names yet, supply "
        "`task_description` with a summary of what you need — "
        "focus areas will be derived automatically.\n"
        "- Call WITHOUT `focus_areas` or `task_description` only "
        "for initial structure discovery of an unfamiliar file.\n"
        "\n"
        "### When to use `read_file` instead\n"
        "- The file is small (< ~50 lines) and you need the "
        "whole thing.\n"
        "- You need exact full-file content (e.g. creating a "
        "copy, auditing every line).\n"
        "- The user explicitly asks to see the full file.\n"
        "\n"
        "### Deriving focus_areas from the task\n"
        "Scan the task text for: function/class names, dotted "
        "identifiers (pkg.mod.Class), quoted symbols, error "
        "names (UserNotFoundError), test names "
        "(test_auth_flow), snake_case identifiers "
        "(process_data), camelCase (handleRequest), "
        "PascalCase (UserService), and config keys. "
        "Pass these as `focus_areas`."
    )


def _handle_read_relevant_command(command: str, name: str) -> str | bool | None:
    if name != "read-relevant":
        return None

    # Very simple CLI: /read-relevant path/to/file.py focus1,focus2
    parts = command.split(maxsplit=2)
    if len(parts) < 2:
        return "Usage: /read-relevant <file_path> [focus_area1,focus_area2,...]"

    file_path = parts[1]
    focus = None
    if len(parts) > 2:
        focus = [f.strip() for f in parts[2].split(",") if f.strip()]

    result = read_relevant_code(file_path, focus_areas=focus)
    if result.error:
        return f"Error: {result.error}"
    emit_info(result.content or "")
    return True


def _custom_command_help() -> list[tuple[str, str]]:
    return [
        (
            "/read-relevant",
            "Read only relevant sections of a file using AST analysis",
        )
    ]


# ---------------------------------------------------------------------------
# Module-scope registration (executed on import by the plugin loader)
# ---------------------------------------------------------------------------

# Guard: if disabled, register no-ops so we don't pollute the system prompt
# or tool registry.
if get_context_reader_enabled():
    register_callback("register_tools", _register_read_relevant_tool)
    register_callback("load_prompt", _load_context_reader_prompt)
    register_callback("custom_command", _handle_read_relevant_command)
    register_callback("custom_command_help", _custom_command_help)
    logger.info("Context-aware reader plugin registered (enabled)")
else:
    register_callback("register_tools", _register_read_relevant_tool_disabled)
    logger.info("Context-aware reader plugin registered (disabled — no tools/prompts)")


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
    if not get_context_reader_enabled():
        logger.info("Context-aware reader disabled via config")
        return

    register_callback("register_tools", _register_read_relevant_tool)
    register_callback("load_prompt", _load_context_reader_prompt)
    register_callback("custom_command", _handle_read_relevant_command)
    register_callback("custom_command_help", _custom_command_help)
    logger.info("Context-aware reader plugin registered via register_all_callbacks()")
