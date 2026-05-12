"""Visibility helpers for auto-review — emit visible status messages."""

import logging

from code_muse.messaging import emit_info, emit_success, emit_warning

logger = logging.getLogger(__name__)


def emit_review_started(file_path: str) -> None:
    """Emit a visible message that review is starting."""
    emit_info(f"🔍 Auto-review in progress... ({file_path})")


def emit_review_approved(file_path: str, summary: str) -> None:
    """Emit a success message when review passes."""
    emit_success(f"✅ Auto-review passed: {summary}")


def emit_review_flagged(file_path: str, summary: str, issues: list[str]) -> None:
    """Emit a warning when review flags issues."""
    msg = f"⚠️ Auto-review: {summary}"
    for issue in issues:
        msg += f"\n  • {issue}"
    emit_warning(msg)


def emit_review_rejected(file_path: str, summary: str, issues: list[str]) -> None:
    """Emit an error when review rejects the change."""
    from code_muse.messaging import emit_error

    msg = f"❌ Auto-review rejected: {summary}"
    for issue in issues:
        msg += f"\n  • {issue}"
    emit_error(msg)


def emit_review_skipped(reason: str) -> None:
    """Emit info when review is skipped."""
    emit_info(f"⏭️ Auto-review skipped: {reason}")


def emit_review_error(file_path: str, error_msg: str) -> None:
    """Emit warning when the review itself fails."""
    emit_warning(f"⚠️ Auto-review error for {file_path}: {error_msg}")
