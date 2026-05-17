"""read_smart tool registration."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from code_muse.plugins.smart_output_compressor.compressor import compress_file_lines
from code_muse.plugins.smart_output_compressor.config import get_enabled, get_max_lines
from code_muse.plugins.smart_output_compressor.metrics import get_metrics
from code_muse.tools.file_operations import ReadFileOutput
from code_muse.tools.path_policy import Operation, check_path_allowed

logger = logging.getLogger(__name__)


def _read_smart_tool_impl(
    context: Any,
    file_path: str,
    focus_areas: list[str] | None = None,
    max_lines: int | None = None,
) -> ReadFileOutput:
    """Read a file smartly: compress output by keeping imports + relevant signatures.

    Use this instead of read_file when you need to understand the structure
    of a file without seeing every line. Focus areas help tailor the output.

    Args:
        file_path: Path to the file to read.
        focus_areas: Optional list of topics to prioritize keeping
            (e.g., ["auth", "login", "UserModel"]).
        max_lines: Maximum lines in the compressed output (default: configured max).
    """
    if not get_enabled():
        return ReadFileOutput(
            content="[smart compressor disabled — use read_file]",
            num_tokens=5,
            error=None,
        )

    # Enforce path policy exactly like read_file
    path = Path(file_path)
    policy = check_path_allowed(str(path), Operation.READ)
    if not policy.allowed:
        return ReadFileOutput(
            content=None,
            num_tokens=0,
            error=policy.reason or "Access denied by path policy",
        )

    try:
        code = path.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return ReadFileOutput(
            content=None, num_tokens=0, error=f"File not found: {file_path}"
        )
    except Exception as exc:
        return ReadFileOutput(content=None, num_tokens=0, error=str(exc))

    effective_max = max_lines or get_max_lines()
    effective_focus = focus_areas or []

    result = compress_file_lines(code, file_path, effective_focus, effective_max)
    get_metrics().record(result)

    num_tokens = max(1, len(result.raw_output) // 4)
    return ReadFileOutput(
        content=result.raw_output,
        num_tokens=num_tokens,
        error=None,
    )


def register_tools() -> list[dict[str, Any]]:
    """Return tool definitions for the central tool registry.

    ``on_register_tools()`` expects each callback to return a list of
    dicts with ``{"name": str, "register_func": callable}`` where
    *register_func(agent)* registers a pydantic-ai tool via ``@agent.tool``.
    """

    def _register_func(agent: Any) -> None:
        """Register the tool with a pydantic-ai agent via @agent.tool."""
        agent.tool(_read_smart_tool_impl)

    return [{"name": "read_smart", "register_func": _register_func}]
