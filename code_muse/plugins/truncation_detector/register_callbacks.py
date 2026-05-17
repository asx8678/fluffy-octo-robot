"""Hook registration for the Truncation Detector plugin.

Registers:
    - ``post_tool_call`` — Detect truncation in file-writing tool results
    - ``pre_tool_call`` — Gate critic/reviewer tool calls on truncated content
    - ``custom_command`` — ``/truncation-detector`` family of slash commands
    - ``custom_command_help`` — Help entries for ``/truncation-detector``

Integration
-----------
Other plugins import :func:`detect_truncation` or :func:`is_truncated` from
the public API (``code_muse.plugins.truncation_detector``) for their own
pre-checks.  This module handles the Muse callback integration.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from code_muse.callbacks import register_callback
from code_muse.plugins.truncation_detector.detector import (
    detect_truncation,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module state
# ---------------------------------------------------------------------------

_enabled: bool = True
_detection_count: int = 0
_blocked_count: int = 0

# Critic / reviewer tool names that should be gated
_CRITIC_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "request_code_review",
        "request_review",
        "review_code",
        "code_review",
        "auto_review",
        "critique_code",
        "critic_review",
    }
)

# File-writing tool names whose output should be checked
_FILE_WRITE_TOOLS: frozenset[str] = frozenset(
    {
        "create_file",
        "replace_in_file",
        "edit_file",
    }
)


def _reset_state() -> None:
    """Reset in-memory counters (used by /truncation-detector reset and startup)."""
    global _detection_count, _blocked_count
    _detection_count = 0
    _blocked_count = 0


# ---------------------------------------------------------------------------
# Helper: emit metric to upgrade_metrics (graceful if unavailable)
# ---------------------------------------------------------------------------


def _emit_metric(data: dict[str, Any]) -> None:
    """Try to emit a ``truncation_detected`` event to upgrade_metrics."""
    try:
        from code_muse.plugins.upgrade_metrics import emit_metric

        emit_metric("truncation_detected", data)
    except ImportError:
        pass  # upgrade_metrics not available — skip silently


# ---------------------------------------------------------------------------
# Startup / Shutdown hooks
# ---------------------------------------------------------------------------


def _on_startup() -> None:
    """Initialize plugin state on startup."""
    global _enabled
    _enabled = True
    _reset_state()
    logger.debug("Truncation Detector plugin initialized")


def _on_shutdown() -> None:
    """Log final stats at debug level on shutdown."""
    logger.debug(
        "Truncation Detector shutting down — detections: %d, blocks: %d",
        _detection_count,
        _blocked_count,
    )


# ---------------------------------------------------------------------------
# pre_tool_call hook — gate critic tool calls
# ---------------------------------------------------------------------------


async def _on_pre_tool_call(
    tool_name: str,
    tool_args: dict,
    context: Any = None,
) -> dict | None:
    """Gate critic tool calls with fast truncation detection.

    If the tool is a critic tool and the file it would review appears
    truncated, return ``{"blocked": True, "reason": "..."}`` to prevent
    the LLM call.  Otherwise return ``None`` to allow execution.
    """
    global _detection_count, _blocked_count

    if not _enabled:
        return None

    # Only gate known critic tools
    if tool_name not in _CRITIC_TOOL_NAMES:
        return None

    # Extract the file_path from tool_args
    file_path = _extract_file_path(tool_args)
    if not file_path:
        return None  # No file to check — allow the call

    # Read the file from disk to check for truncation
    content = _read_file_content(file_path)
    if content is None:
        return None  # Can't read — allow the call (don't block on I/O errors)

    result = detect_truncation(content, file_path=file_path)
    _detection_count += 1

    if result.is_truncated:
        _blocked_count += 1
        logger.info(
            "Truncation detected — blocking %s on %s: %s (%s)",
            tool_name,
            file_path,
            result.reason,
            result.method,
        )

        _emit_metric(
            {
                "tool_name": tool_name,
                "file_path": file_path,
                "method": result.method,
                "reason": result.reason,
                "blocked_critic_call": True,
            }
        )

        return {
            "blocked": True,
            "reason": (
                f"Truncation detected ({result.method}): {result.reason}. "
                f"Skipping LLM review to save tokens."
            ),
        }

    return None


# ---------------------------------------------------------------------------
# post_tool_call hook — flag truncated file writes
# ---------------------------------------------------------------------------


async def _on_post_tool_call(
    tool_name: str,
    tool_args: dict,
    result: Any,
    duration_ms: float,
    context: Any = None,
) -> None:
    """Detect truncation in files written by file-writing tools.

    After a file-write completes, reads the file from disk and checks
    for truncation.  Emits a warning and metric if detected, but does
    NOT block the tool call (it already happened).
    """
    global _detection_count

    if not _enabled:
        return

    # Only check file-writing tools
    if tool_name not in _FILE_WRITE_TOOLS:
        return

    file_path = _extract_file_path(tool_args)
    if not file_path:
        return

    content = _read_file_content(file_path)
    if content is None:
        return

    trunc_result = detect_truncation(content, file_path=file_path)
    _detection_count += 1

    if trunc_result.is_truncated:
        from code_muse.messaging import emit_warning

        emit_warning(
            f"⚠️ Truncation detected in {file_path}: "
            f"{trunc_result.reason} ({trunc_result.method})"
        )

        _emit_metric(
            {
                "tool_name": tool_name,
                "file_path": file_path,
                "method": trunc_result.method,
                "reason": trunc_result.reason,
                "blocked_critic_call": False,
            }
        )


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------


def _extract_file_path(tool_args: dict) -> str:
    """Extract file_path from tool arguments."""
    val = tool_args.get("file_path") or tool_args.get("path") or ""
    return str(val) if val else ""


def _read_file_content(file_path: str) -> str | None:
    """Read file content from disk, returning ``None`` if not found."""
    try:
        p = Path(file_path).expanduser().resolve()
        if p.is_file():
            return p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        logger.debug("Could not read %s for truncation check", file_path)
    return None


# ---------------------------------------------------------------------------
# Custom commands — /truncation-detector family
# ---------------------------------------------------------------------------


def _on_custom_command(command: str, name: str) -> bool | None:
    """Handle ``/truncation-detector`` family of slash commands.

    Also accepts ``/truncation`` as a shorter alias.

    Commands:
        /truncation-detector status  — Show detection stats
        /truncation-detector off     — Disable truncation gating
        /truncation-detector on      — Re-enable truncation gating
        /truncation-detector reset   — Reset in-memory counters
        /truncation-detector help    — Show available commands
    """
    global _enabled

    if name not in ("truncation-detector", "truncation"):
        return None

    parts = command.split(maxsplit=1)
    sub = parts[1].strip().lower() if len(parts) > 1 else "status"

    if sub == "off":
        _enabled = False
        from code_muse.messaging import emit_warning

        emit_warning("🔍 Truncation detection disabled")
        return True

    if sub == "on":
        _enabled = True
        from code_muse.messaging import emit_success

        emit_success("🔍 Truncation detection enabled")
        return True

    if sub == "reset":
        _reset_state()
        from code_muse.messaging import emit_success

        emit_success("🔍 Truncation detection counters reset")
        return True

    if sub == "status":
        from code_muse.messaging import emit_info

        state = "enabled" if _enabled else "disabled"
        lines = [
            f"🔍 Truncation Detector Status: {state}",
            f"   Detections run: {_detection_count}",
            f"   Critic calls blocked: {_blocked_count}",
        ]
        emit_info("\n".join(lines))
        return True

    if sub == "help" or sub == "":
        from code_muse.messaging import emit_info

        lines = [
            "🔍 Truncation Detector Commands:",
            "   /truncation-detector status  — Show detection stats",
            "   /truncation-detector off     — Disable truncation gating",
            "   /truncation-detector on      — Re-enable truncation gating",
            "   /truncation-detector reset   — Reset in-memory counters",
            "   /truncation-detector help    — Show this help",
        ]
        emit_info("\n".join(lines))
        return True

    from code_muse.messaging import emit_info

    emit_info("Usage: /truncation-detector status|off|on|reset|help")
    return True


def _on_custom_command_help() -> list[tuple[str, str]]:
    """Return help entries for the /truncation-detector command family."""
    return [
        ("truncation-detector status", "Show truncation detection stats"),
        ("truncation-detector off", "Disable truncation detection gating"),
        ("truncation-detector on", "Re-enable truncation detection gating"),
        ("truncation-detector reset", "Reset truncation detection counters"),
        ("truncation-detector help", "Show truncation detector commands"),
    ]


# ---------------------------------------------------------------------------
# Register all callbacks
# ---------------------------------------------------------------------------

register_callback("startup", _on_startup)
register_callback("shutdown", _on_shutdown)
register_callback("pre_tool_call", _on_pre_tool_call)
register_callback("post_tool_call", _on_post_tool_call)
register_callback("custom_command", _on_custom_command)
register_callback("custom_command_help", _on_custom_command_help)

logger.debug("Truncation Detector plugin callbacks registered")
