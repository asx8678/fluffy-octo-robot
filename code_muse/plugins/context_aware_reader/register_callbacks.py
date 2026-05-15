"""Plugin registration for the Context-Aware Code Reader.

Registers:
- The `read_relevant_code` tool
- Tool metadata (non-destructive, file_ops category)
- System prompt guidance telling the model when to prefer this tool over raw `read_file`
- `/read-relevant` custom command for manual use
"""

import logging
from typing import Any

from code_muse.callbacks import register_callback
from code_muse.messaging import emit_info
from code_muse.plugins.context_aware_reader.config import (
    get_context_reader_enabled,
)
from code_muse.plugins.context_aware_reader.reader import read_relevant_code
from code_muse.tools.file_operations import ReadFileOutput

logger = logging.getLogger(__name__)


def register_all_callbacks() -> None:
    """Called by the plugin loader."""
    if not get_context_reader_enabled():
        logger.info("Context-aware reader disabled via config")
        return

    register_callback("register_tools", _register_read_relevant_tool)
    register_callback("register_tool_metadata", _register_tool_metadata)
    register_callback("load_prompt", _load_context_reader_prompt)
    register_callback("custom_command", _handle_read_relevant_command)
    register_callback("custom_command_help", _custom_command_help)

    logger.info("Context-aware reader plugin registered")


def _register_read_relevant_tool(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Register the tool with the central tool registry."""

    def read_relevant_code_tool(
        context: Any,
        file_path: str,
        focus_areas: list[str] | None = None,
    ) -> ReadFileOutput:
        """Read only the most relevant sections of a file for the current task.

        Dramatically more token-efficient than full read_file when you only
        need specific functions, classes, or areas related to a task.
        """
        return read_relevant_code(file_path, focus_areas=focus_areas)

    tools.append(
        {
            "name": "read_relevant_code",
            "func": read_relevant_code_tool,
            "description": (
                "Read relevant portions of a source file using AST analysis. "
                "Use this instead of read_file when you only need specific functions, "
                "classes or areas related to the current task. "
                "Always include imports. Returns line-numbered output."
            ),
            "parameters": {
                "file_path": {
                    "type": "string",
                    "description": "Path to the source file",
                },
                "focus_areas": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional list of function/class names or keywords to focus on",
                },
            },
        }
    )
    return tools


def _register_tool_metadata(metadata: list[dict]) -> list[dict]:
    metadata.append(
        {
            "name": "read_relevant_code",
            "destructive": False,
            "idempotent": True,
            "category": "file_ops",
            "requires_confirmation": False,
            "description": "Read relevant code sections only (AST-powered)",
        }
    )
    return metadata


def _load_context_reader_prompt() -> str | None:
    """Inject guidance into the system prompt so the model knows when to use the tool."""
    return (
        "\n\n## Context-Aware Code Reader\n"
        "When you need to understand code in a large file, prefer the "
        "`read_relevant_code` tool over `read_file`. It uses AST parsing to return "
        "only the functions, classes and imports relevant to the current task, "
        "saving many thousands of tokens. "
        'Provide `focus_areas` (e.g. ["process_data", "UserService"]) when you know '
        "what you're looking for. If you don't know the names yet, call it without "
        "focus_areas to get a smart summary of the file structure."
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
        ("/read-relevant", "Read only relevant sections of a file using AST analysis")
    ]
