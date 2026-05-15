"""Tool error tracking circuit breaker.

Tracks consecutive tool errors per-tool-name as a per-agent-run
circuit breaker, so one flaky tool does not abort calls to other
healthy tools.
"""

import contextvars
from typing import Any

from code_muse.callbacks import register_callback


class _ToolErrorTracker:
    """Track consecutive tool errors per-tool-name as a per-agent-run circuit breaker.

    Each tool has its own consecutive-error counter, so one flaky tool (e.g.
    browser screenshot timeout) does not abort calls to other healthy tools.

    A global max_total_tool_errors acts as a safety net to prevent unbounded
    total errors across all tools.
    """

    def __init__(self, max_errors: int = 3, max_total_errors: int = 20):
        self.max_errors = max_errors
        self.max_total_errors = max_total_errors
        self.consecutive_errors: dict[str, int] = {}
        self.total_errors: int = 0

    def record_error(self, tool_name: str) -> bool:
        """Increment error count for *tool_name*. Returns True if max exceeded."""
        count = self.consecutive_errors.get(tool_name, 0) + 1
        self.consecutive_errors[tool_name] = count
        self.total_errors += 1
        if self.total_errors >= self.max_total_errors:
            return True
        return count >= self.max_errors

    def record_success(self, tool_name: str) -> None:
        """Reset error count for *tool_name* on a successful tool call."""
        self.consecutive_errors.pop(tool_name, None)


_tool_error_tracker_ctx: contextvars.ContextVar[_ToolErrorTracker | None] = (
    contextvars.ContextVar("_tool_error_tracker_ctx", default=None)
)


async def _track_pre_tool_call(
    tool_name: str,
    tool_args: dict,
    context: Any = None,
) -> dict | None:
    """Block tool calls once the consecutive-error cap is hit."""
    tracker = _tool_error_tracker_ctx.get()
    if tracker is None:
        return None
    tool_errors = tracker.consecutive_errors.get(tool_name, 0)
    if tool_errors >= tracker.max_errors:
        return {
            "blocked": True,
            "reason": (
                f"Too many consecutive errors ({tool_errors}) for tool "
                f"'{tool_name}' — blocking further calls."
            ),
        }
    if tracker.total_errors >= tracker.max_total_errors:
        return {
            "blocked": True,
            "reason": (
                f"Too many total tool errors ({tracker.total_errors}) — aborting run."
            ),
        }
    return None


async def _track_post_tool_call(
    tool_name: str,
    tool_args: dict,
    result: Any,
    duration_ms: float,
    context: Any = None,
) -> None:
    """Count consecutive tool errors via a contextvar (per-run state)."""
    tracker = _tool_error_tracker_ctx.get()
    if tracker is None:
        return None
    if isinstance(result, dict) and "error" in result:
        tracker.record_error(tool_name)
    else:
        tracker.record_success(tool_name)
    return None


# Register callbacks at module load time.
register_callback("pre_tool_call", _track_pre_tool_call)
register_callback("post_tool_call", _track_post_tool_call)
