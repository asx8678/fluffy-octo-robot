"""Register slash commands and startup hook for the token-tracking plugin.

Commands:
    /tracking gain [today|week|month|all]
    /tracking cc-economics [today|week|month|all]
    /tracking session [N]
    /tracking edit-efficiency [today|week|month|all]
    /tracking help
"""

import logging
from typing import Any

from code_muse.callbacks import register_callback
from code_muse.config import get_current_autosave_id
from code_muse.messaging import emit_info
from code_muse.plugins.token_tracking.database import TrackingDatabase, get_tracking_db
from code_muse.plugins.token_tracking.edit_analyzer import analyze_replacement
from code_muse.plugins.token_tracking.reports import (
    cc_economics_report,
    edit_efficiency_report,
    gain_report,
    session_report,
)

logger = logging.getLogger(__name__)


def _get_db() -> TrackingDatabase:
    """Return the shared ``TrackingDatabase`` instance."""
    return get_tracking_db()


# ------------------------------------------------------------------
# Startup hook
# ------------------------------------------------------------------


def _on_startup() -> None:
    """Run database cleanup on application startup."""
    try:
        db = _get_db()
        removed = db.cleanup()
        logger.debug("Token tracking startup cleanup removed %s rows", removed)
    except Exception:
        pass


# ------------------------------------------------------------------
# Post-tool-call hook (edit efficiency tracking)
# ------------------------------------------------------------------


def _on_post_tool_call(
    tool_name: str,
    tool_args: dict[str, Any],
    result: Any,
    duration_ms: float,
    context: Any = None,
) -> Any:
    """Intercept file-edit tools to measure context inflation.

    Analyses ``create_file``, ``replace_in_file``, and ``delete_snippet``
    calls, stores byte-level metrics, and returns *None* so the tool
    result is left untouched.
    """
    if tool_name not in ("create_file", "replace_in_file", "delete_snippet"):
        return None

    try:
        file_path = tool_args.get("file_path", "")
        success = True
        if isinstance(result, dict) and result.get("error"):
            success = False

        if tool_name == "create_file":
            old_text = ""
            new_text = tool_args.get("content", "")
            _store_edit_analysis(tool_name, file_path, old_text, new_text, success)

        elif tool_name == "delete_snippet":
            old_text = tool_args.get("snippet", "")
            new_text = ""
            _store_edit_analysis(tool_name, file_path, old_text, new_text, success)

        elif tool_name == "replace_in_file":
            replacements = tool_args.get("replacements", [])
            if not replacements:
                return None

            # Aggregate across all replacements in this call (Pi style)
            totals: dict[str, int] = {
                "old_bytes": 0,
                "new_bytes": 0,
                "total_edit_bytes": 0,
                "shared_prefix_bytes": 0,
                "shared_suffix_bytes": 0,
                "shared_context_bytes": 0,
                "core_old_bytes": 0,
                "core_new_bytes": 0,
                "core_bytes": 0,
                "wrapper_payload_bytes": 0,
            }
            has_core_change = False
            total_core = 0
            total_edit = 0

            for rep in replacements:
                old_text = rep.get("old_text", "")
                new_text = rep.get("new_text", "")
                analysis = analyze_replacement(old_text, new_text)

                for key in totals:
                    totals[key] += analysis[key]

                if not analysis["no_core_change"]:
                    has_core_change = True
                total_core += analysis["core_bytes"]
                total_edit += analysis["total_edit_bytes"]

            no_core_change = not has_core_change
            inflation_ratio = (
                None
                if no_core_change
                else (total_edit / total_core if total_core else None)
            )

            db = _get_db()
            db.insert_edit_analysis(
                tool_name=tool_name,
                file_path=file_path,
                old_bytes=totals["old_bytes"],
                new_bytes=totals["new_bytes"],
                total_edit_bytes=totals["total_edit_bytes"],
                shared_prefix_bytes=totals["shared_prefix_bytes"],
                shared_suffix_bytes=totals["shared_suffix_bytes"],
                shared_context_bytes=totals["shared_context_bytes"],
                core_old_bytes=totals["core_old_bytes"],
                core_new_bytes=totals["core_new_bytes"],
                core_bytes=totals["core_bytes"],
                wrapper_payload_bytes=totals["wrapper_payload_bytes"],
                inflation_ratio=inflation_ratio,
                no_core_change=no_core_change,
                success=success,
                session_id=get_current_autosave_id(),
            )

    except Exception:
        logger.debug("Edit efficiency tracking failed for %s", tool_name, exc_info=True)

    return None


def _store_edit_analysis(
    tool_name: str,
    file_path: str,
    old_text: str,
    new_text: str,
    success: bool,
) -> None:
    """Analyze a single replacement and store it in the database."""
    analysis = analyze_replacement(old_text, new_text)
    db = _get_db()
    db.insert_edit_analysis(
        tool_name=tool_name,
        file_path=file_path,
        old_bytes=analysis["old_bytes"],
        new_bytes=analysis["new_bytes"],
        total_edit_bytes=analysis["total_edit_bytes"],
        shared_prefix_bytes=analysis["shared_prefix_bytes"],
        shared_suffix_bytes=analysis["shared_suffix_bytes"],
        shared_context_bytes=analysis["shared_context_bytes"],
        core_old_bytes=analysis["core_old_bytes"],
        core_new_bytes=analysis["core_new_bytes"],
        core_bytes=analysis["core_bytes"],
        wrapper_payload_bytes=analysis["wrapper_payload_bytes"],
        inflation_ratio=analysis["inflation_ratio"],
        no_core_change=analysis["no_core_change"],
        success=success,
        session_id=get_current_autosave_id(),
    )


# ------------------------------------------------------------------
# Help
# ------------------------------------------------------------------


def _on_custom_command_help() -> list[tuple[str, str]]:
    """Provide help entries for /help display."""
    return [
        ("tracking gain [time]", "Token savings report (today/week/month/all)"),
        ("tracking cc-economics [time]", "Estimated Claude Code dollar savings"),
        ("tracking session [N]", "Per-session adoption stats (default 10)"),
        (
            "tracking edit-efficiency [time]",
            "Edit context-inflation / efficiency report",
        ),
    ]


# ------------------------------------------------------------------
# Slash-command handler
# ------------------------------------------------------------------


async def _on_custom_command(command: str, name: str) -> bool | None:
    """Handle ``/tracking …`` slash commands.

    Args:
        command: Full command string (e.g. ``/tracking gain week``).
        name: First token after the slash (always ``tracking`` here).

    Returns:
        ``True`` if handled, ``None`` if not a tracking command.
    """
    if name != "tracking":
        return None

    tokens = command.strip().split()
    subcommand = tokens[1] if len(tokens) > 1 else "help"
    arg = tokens[2] if len(tokens) > 2 else None

    db = _get_db()

    if subcommand in ("help",):
        emit_info(
            "Available /tracking commands:\n"
            "  /tracking gain [today|week|month|all]\n"
            "  /tracking cc-economics [today|week|month|all]\n"
            "  /tracking session [N]\n"
            "  /tracking help"
        )
        return True

    if subcommand == "gain":
        time_range = arg or "all"
        report = gain_report(db, time_range)
        emit_info(report)
        return True

    if subcommand == "cc-economics":
        time_range = arg or "all"
        report = cc_economics_report(db, time_range)
        emit_info(report)
        return True

    if subcommand == "session":
        limit = int(arg) if arg is not None and arg.isdigit() else 10
        report = session_report(db, limit)
        emit_info(report)
        return True

    if subcommand == "edit-efficiency":
        time_range = arg or "all"
        report = edit_efficiency_report(db, time_range)
        emit_info(report)
        return True

    # Unknown subcommand — still consumed by this plugin
    emit_info(
        f"Unknown /tracking subcommand: {subcommand}\n"
        "Try /tracking help for available commands."
    )
    return True


# ------------------------------------------------------------------
# Register
# ------------------------------------------------------------------

register_callback("startup", _on_startup)
register_callback("custom_command_help", _on_custom_command_help)
register_callback("custom_command", _on_custom_command)
register_callback("post_tool_call", _on_post_tool_call)

logger.debug("Token Tracking plugin callbacks registered")
