"""Callback registration for the Auto-Review plugin.

Registers:
    - ``post_tool_call`` hook — automatically reviews file changes
    - ``request_code_review`` tool — manual review trigger
"""

import logging
from typing import Any

from code_muse.callbacks import register_callback
from code_muse.plugins.auto_review.reviewer import (
    request_manual_review,
    run_auto_review,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# post_tool_call hook
# ---------------------------------------------------------------------------


async def _on_post_tool_call(
    tool_name: str,
    tool_args: dict,
    result: dict,
    duration_ms: float,
    context: Any = None,
) -> None:
    """Review file changes after tool execution."""
    try:
        await run_auto_review(tool_name, tool_args, result)
    except Exception as exc:
        logger.error("Auto-review hook failed: %s", exc, exc_info=True)


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------


def _register_review_tools() -> list[dict]:
    """Return tool definitions for the auto-review plugin."""

    def register_request_code_review(agent):
        """Register the request_code_review tool on an agent."""

        @agent.tool
        async def request_code_review(
            context,
            file_path: str = "",
            reason: str | None = None,
        ) -> dict:
            """Request a code review for a specific file.

            The reviewer analyzes the file for correctness, safety, style,
            edge cases, and completeness. Returns structured feedback.

            Args:
                file_path: Path to the file to review
                reason: Optional focus area for the review \
                    (e.g., "security", "performance")

            Returns:
                Dict with verdict, summary, issues, and suggestion
            """
            return await request_manual_review(file_path, reason)

    return [
        {
            "name": "request_code_review",
            "register_func": register_request_code_review,
        },
    ]


# ---------------------------------------------------------------------------
# Help entry
# ---------------------------------------------------------------------------


def _on_custom_command_help() -> list[tuple[str, str]]:
    return [
        ("review <path>", "Request an auto-review for a specific file"),
    ]


def _on_custom_command(command: str, name: str) -> bool | None:
    """Handle ``/review <path>`` command."""
    if name == "review":
        parts = command.split(maxsplit=1)
        file_path = parts[1].strip() if len(parts) > 1 else ""
        if not file_path:
            from code_muse.messaging import emit_warning

            emit_warning("Usage: /review <file_path>")
            return True

        import asyncio

        try:
            loop = asyncio.get_running_loop()
            loop.create_task(request_manual_review(file_path))
        except RuntimeError:
            asyncio.run(request_manual_review(file_path))

        return True
    return None


# ---------------------------------------------------------------------------
# Register all callbacks
# ---------------------------------------------------------------------------

register_callback("post_tool_call", _on_post_tool_call)
register_callback("register_tools", _register_review_tools)
register_callback("custom_command_help", _on_custom_command_help)
register_callback("custom_command", _on_custom_command)

logger.debug("Auto-Review plugin callbacks registered")
