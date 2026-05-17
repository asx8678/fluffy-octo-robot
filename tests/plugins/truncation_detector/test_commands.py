"""Tests for the Truncation Detector slash commands and hook integration.

These tests exercise the ``register_callbacks`` module — command handling,
enable/disable state, and pre_tool_call gating.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from code_muse.plugins.truncation_detector import register_callbacks as rb

# ============================================================================
# Helpers
# ============================================================================


def _run_async(coro):
    """Run an async coroutine synchronously in a fresh event loop."""
    import asyncio

    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture(autouse=True)
def _reset_state():
    """Ensure clean state before and after each test."""
    rb._enabled = True
    rb._reset_state()
    yield
    rb._enabled = True
    rb._reset_state()


# ============================================================================
# Custom command — /truncation status
# ============================================================================


class TestStatusCommand:
    """Tests for ``/truncation status``."""

    def test_returns_true(self) -> None:
        with patch("code_muse.messaging.emit_info"):
            result = rb._on_custom_command("/truncation status", "truncation")
            assert result is True

    def test_unknown_prefix_not_consumed(self) -> None:
        result = rb._on_custom_command("/other status", "other")
        assert result is None


# ============================================================================
# Custom command — /truncation off
# ============================================================================


class TestOffCommand:
    """Tests for ``/truncation off``."""

    def test_disables_plugin(self) -> None:
        with patch("code_muse.messaging.emit_warning"):
            rb._on_custom_command("/truncation off", "truncation")
        assert rb._enabled is False

    def test_pre_tool_call_passes_through_when_disabled(self, tmp_path: Path) -> None:
        """When disabled, pre_tool_call should return None (pass-through)."""
        with patch("code_muse.messaging.emit_warning"):
            rb._on_custom_command("/truncation off", "truncation")

        # Even a truncated file should pass through
        truncated_file = tmp_path / "truncated.py"
        truncated_file.write_text("def foo(\n")

        result = _run_async(
            rb._on_pre_tool_call(
                "request_code_review",
                {"file_path": str(truncated_file)},
            )
        )
        assert result is None


# ============================================================================
# Custom command — /truncation on
# ============================================================================


class TestOnCommand:
    """Tests for ``/truncation on``."""

    def test_reenables_plugin(self) -> None:
        with patch("code_muse.messaging.emit_warning"):
            rb._on_custom_command("/truncation off", "truncation")
        assert rb._enabled is False
        with patch("code_muse.messaging.emit_success"):
            rb._on_custom_command("/truncation on", "truncation")
        assert rb._enabled is True


# ============================================================================
# Custom command — /truncation reset
# ============================================================================


class TestResetCommand:
    """Tests for ``/truncation reset``."""

    def test_resets_counters(self) -> None:
        # Simulate some detections by direct assignment
        rb._detection_count = 10
        rb._blocked_count = 5
        with patch("code_muse.messaging.emit_success"):
            rb._on_custom_command("/truncation reset", "truncation")
        assert rb._detection_count == 0
        assert rb._blocked_count == 0


# ============================================================================
# Custom command — /truncation-detector alias
# ============================================================================


class TestTruncationDetectorAlias:
    """Tests for the ``/truncation-detector`` command alias."""

    def test_off_alias(self) -> None:
        with patch("code_muse.messaging.emit_warning"):
            result = rb._on_custom_command(
                "/truncation-detector off", "truncation-detector"
            )
        assert result is True
        assert rb._enabled is False


# ============================================================================
# Custom command — help
# ============================================================================


class TestHelpCommand:
    """Tests for ``/truncation help`` and custom_command_help."""

    def test_help_returns_true(self) -> None:
        with patch("code_muse.messaging.emit_info"):
            result = rb._on_custom_command("/truncation help", "truncation")
        assert result is True

    def test_bare_truncation_returns_true(self) -> None:
        with patch("code_muse.messaging.emit_info"):
            result = rb._on_custom_command("/truncation", "truncation")
        assert result is True

    def test_custom_command_help_returns_list(self) -> None:
        entries = rb._on_custom_command_help()
        assert isinstance(entries, list)
        assert all(isinstance(e, tuple) and len(e) == 2 for e in entries)
        assert len(entries) > 0


# ============================================================================
# Custom command — unknown sub-commands
# ============================================================================


class TestUnknownCommand:
    """Tests for unknown sub-commands — should still consume (return True)."""

    def test_unknown_subcmd_returns_true(self) -> None:
        with patch("code_muse.messaging.emit_info"):
            result = rb._on_custom_command("/truncation foobar", "truncation")
        assert result is True

    def test_unknown_name_not_consumed(self) -> None:
        result = rb._on_custom_command("/unknown status", "unknown")
        assert result is None


# ============================================================================
# pre_tool_call hook
# ============================================================================


class TestPreToolCallHook:
    """Tests for the ``pre_tool_call`` gating hook."""

    def test_blocks_truncated_file(self, tmp_path: Path) -> None:
        truncated_file = tmp_path / "truncated.py"
        truncated_file.write_text("def foo(\n")

        result = _run_async(
            rb._on_pre_tool_call(
                "request_code_review",
                {"file_path": str(truncated_file)},
            )
        )
        assert result is not None
        assert result.get("blocked") is True

    def test_allows_non_truncated_file(self, tmp_path: Path) -> None:
        valid_file = tmp_path / "valid.py"
        valid_file.write_text("def foo():\n    return 42\n")

        result = _run_async(
            rb._on_pre_tool_call(
                "request_code_review",
                {"file_path": str(valid_file)},
            )
        )
        assert result is None

    def test_ignores_non_critic_tools(self, tmp_path: Path) -> None:
        truncated_file = tmp_path / "truncated.py"
        truncated_file.write_text("def foo(\n")

        result = _run_async(
            rb._on_pre_tool_call(
                "read_file",
                {"file_path": str(truncated_file)},
            )
        )
        assert result is None

    def test_ignores_when_disabled(self, tmp_path: Path) -> None:
        rb._enabled = False
        truncated_file = tmp_path / "truncated.py"
        truncated_file.write_text("def foo(\n")

        result = _run_async(
            rb._on_pre_tool_call(
                "request_code_review",
                {"file_path": str(truncated_file)},
            )
        )
        assert result is None

    def test_no_file_path_passes_through(self) -> None:
        result = _run_async(
            rb._on_pre_tool_call(
                "request_code_review",
                {},  # no file_path key
            )
        )
        assert result is None

    def test_increments_detection_count(self, tmp_path: Path) -> None:
        valid_file = tmp_path / "valid.py"
        valid_file.write_text("def foo():\n    return 42\n")

        _run_async(
            rb._on_pre_tool_call(
                "request_code_review",
                {"file_path": str(valid_file)},
            )
        )
        assert rb._detection_count == 1

    def test_increments_block_count_on_truncation(self, tmp_path: Path) -> None:
        truncated_file = tmp_path / "truncated.py"
        truncated_file.write_text("def foo(\n")

        _run_async(
            rb._on_pre_tool_call(
                "request_code_review",
                {"file_path": str(truncated_file)},
            )
        )
        assert rb._blocked_count == 1

    def test_all_critic_tool_names_gated(self, tmp_path: Path) -> None:
        """Each critic tool name should be gated on truncated files."""
        truncated_file = tmp_path / "truncated.py"
        truncated_file.write_text("def foo(\n")

        for tool_name in rb._CRITIC_TOOL_NAMES:
            rb._reset_state()
            result = _run_async(
                rb._on_pre_tool_call(
                    tool_name,
                    {"file_path": str(truncated_file)},
                )
            )
            assert result is not None and result.get("blocked") is True, (
                f"Tool {tool_name!r} was not gated"
            )
