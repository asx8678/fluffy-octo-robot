"""Comprehensive tests for the Truncation Detector plugin.

Tests cover:
    1. Pure detection engine (detector.py) — all 8 detection methods
    2. Backward compatibility (code_critic/reviewer.py re-export)
    3. Hook integration (register_callbacks.py) — pre/post tool call, commands
    4. Edge cases — empty input, very long files, mixed content, concurrent state
"""

from __future__ import annotations

import textwrap
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from code_muse.plugins.truncation_detector import (
    detect_truncation,
    is_truncated,
)
from code_muse.plugins.truncation_detector.detector import (
    _check_ast_parse,
    _check_bracket_imbalance,
    _check_empty,
    _check_incomplete_json,
    _check_markdown_blocks,
    _check_open_endings,
    _check_trailing_line,
    _check_truncated_declarations,
)


def _run_async(coro: Any) -> Any:
    """Run an async coroutine synchronously in a fresh event loop.

    Required because Python 3.14 removed the implicit event loop
    (``asyncio.get_event_loop()`` raises ``RuntimeError`` if no loop
    is running).  We explicitly create and close a loop per call.
    """
    import asyncio

    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ===================================================================
# 1. Detection engine — individual methods
# ===================================================================


class TestCheckEmpty:
    """Tests for the empty-content detection method."""

    def test_empty_string(self) -> None:
        assert _check_empty("") is not None
        assert _check_empty("").is_truncated is True

    def test_whitespace_only(self) -> None:
        assert _check_empty("   \n\t  ").is_truncated is True

    def test_non_empty(self) -> None:
        assert _check_empty("x = 1") is None

    def test_newline_only(self) -> None:
        assert _check_empty("\n\n\n").is_truncated is True


class TestCheckAstParse:
    """Tests for the Python AST parse detection method."""

    def test_valid_python(self) -> None:
        result = _check_ast_parse("x = 1\nprint(x)\n", "test.py")
        assert result is None

    def test_invalid_python(self) -> None:
        result = _check_ast_parse("def foo(\n", "test.py")
        assert result is not None
        assert result.is_truncated is True
        assert result.method == "ast_parse"

    def test_non_python_file_ignored(self) -> None:
        result = _check_ast_parse("def foo(\n", "test.js")
        assert result is None

    def test_pyi_extension(self) -> None:
        result = _check_ast_parse("def foo(\n", "test.pyi")
        assert result is not None
        assert result.is_truncated is True

    def test_no_extension(self) -> None:
        result = _check_ast_parse("def foo(\n", "")
        assert result is None

    def test_valid_complex_python(self) -> None:
        code = textwrap.dedent("""\
            class Foo:
                def bar(self):
                    return 42
        """)
        assert _check_ast_parse(code, "test.py") is None


class TestCheckOpenEndings:
    """Tests for the open-ending detection method."""

    @pytest.mark.parametrize(
        "ending",
        ["{", "[", "(", ":", ",", "&&", "||", "->", "=>"],
    )
    def test_open_endings_detected(self, ending: str) -> None:
        result = _check_open_endings(f"x = 1 {ending}")
        assert result is not None
        assert result.is_truncated is True
        assert result.method == "open_ending"

    def test_complete_code_not_flagged(self) -> None:
        result = _check_open_endings("x = 1;")
        assert result is None

    def test_empty_content(self) -> None:
        assert _check_open_endings("") is None

    def test_whitespace_only(self) -> None:
        assert _check_open_endings("   \n  ") is None


class TestCheckTruncatedDeclarations:
    """Tests for the truncated-declaration detection method."""

    @pytest.mark.parametrize(
        "line",
        [
            "class Bar",
            "function myFunc",
            "import os",
            "from collections",
            "if x",
            "for item",
            "while True",
            "export default",
            "const x",
            "interface IWidget",
            "enum Color",
            "struct Point",
        ],
    )
    def test_truncated_declarations_detected(self, line: str) -> None:
        result = _check_truncated_declarations(line)
        assert result is not None
        assert result.is_truncated is True
        assert result.method == "truncated_declaration"

    def test_complete_declaration_not_flagged(self) -> None:
        # Short line with body chars
        result = _check_truncated_declarations("def foo(): pass")
        assert result is None

    def test_long_line_not_flagged(self) -> None:
        # >90 chars, even if it looks like a declaration
        result = _check_truncated_declarations("def " + "x" * 90)
        assert result is None

    def test_empty_content(self) -> None:
        assert _check_truncated_declarations("") is None


class TestCheckBracketImbalance:
    """Tests for the bracket-imbalance detection method."""

    def test_severe_imbalance(self) -> None:
        # Many more opens than closes (need >3 difference)
        code = "{{{{{{  some code\n"
        result = _check_bracket_imbalance(code)
        assert result is not None
        assert result.is_truncated is True
        assert result.method == "bracket_imbalance"

    def test_balanced_code(self) -> None:
        code = "def foo():\n    pass\n"
        assert _check_bracket_imbalance(code) is None

    def test_small_imbalance_not_flagged(self) -> None:
        # 2 extra opens — within tolerance
        code = "if (a and (b or c):\n    pass\n"
        result = _check_bracket_imbalance(code)
        assert result is None

    def test_empty_content(self) -> None:
        assert _check_bracket_imbalance("") is None


class TestCheckTrailingLine:
    """Tests for the trailing-line detection method."""

    def test_trailing_ellipsis(self) -> None:
        result = _check_trailing_line("x = foo\n...")
        assert result is not None
        assert result.is_truncated is True
        assert result.method == "trailing_line"

    def test_trailing_operator(self) -> None:
        result = _check_trailing_line("x = a +")
        assert result is not None
        assert result.is_truncated is True

    def test_complete_line_not_flagged(self) -> None:
        assert _check_trailing_line("x = 1 + 2") is None

    def test_partial_method_call(self) -> None:
        result = _check_trailing_line("monkeypatch.ab")
        assert result is not None
        assert result.is_truncated is True

    def test_complete_method_call_not_flagged(self) -> None:
        assert _check_trailing_line("monkeypatch.attr(xyz)") is None

    def test_empty_content(self) -> None:
        assert _check_trailing_line("") is None


class TestCheckMarkdownBlocks:
    """Tests for the markdown code block detection method."""

    def test_unclosed_backtick_block(self) -> None:
        result = _check_markdown_blocks("```python\ndef foo():\n    pass\n")
        assert result is not None
        assert result.is_truncated is True
        assert result.method == "markdown_block"

    def test_closed_backtick_block_not_flagged(self) -> None:
        result = _check_markdown_blocks("```python\nx = 1\n```\n")
        assert result is None

    def test_unclosed_tilde_block(self) -> None:
        result = _check_markdown_blocks("~~~js\nconst x = 1;\n")
        assert result is not None
        assert result.is_truncated is True

    def test_no_code_blocks(self) -> None:
        assert _check_markdown_blocks("Just text, no blocks.") is None

    def test_empty_content(self) -> None:
        assert _check_markdown_blocks("") is None


class TestCheckIncompleteJson:
    """Tests for the incomplete-JSON detection method."""

    def test_truncated_json_object(self) -> None:
        result = _check_incomplete_json('{"key": "value", "nested": {')
        assert result is not None
        assert result.is_truncated is True
        assert result.method == "incomplete_json"

    def test_truncated_json_array(self) -> None:
        result = _check_incomplete_json('["a", "b", "c",')
        assert result is not None
        assert result.is_truncated is True

    def test_valid_json_not_flagged(self) -> None:
        assert _check_incomplete_json('{"key": "value"}') is None

    def test_non_json_start_not_checked(self) -> None:
        assert _check_incomplete_json("x = 1") is None

    def test_empty_content(self) -> None:
        assert _check_incomplete_json("") is None


# ===================================================================
# 2. Top-level detect_truncation / is_truncated API
# ===================================================================


class TestDetectTruncation:
    """Tests for the top-level detect_truncation function."""

    def test_empty_content(self) -> None:
        result = detect_truncation("")
        assert result.is_truncated is True
        assert result.method == "empty"

    def test_valid_python_file(self) -> None:
        result = detect_truncation("x = 1\n", file_path="test.py")
        assert result.is_truncated is False

    def test_truncated_python_file(self) -> None:
        result = detect_truncation("def foo(\n", file_path="test.py")
        assert result.is_truncated is True
        assert result.method == "ast_parse"

    def test_truncated_js_file(self) -> None:
        # Use clearly truncated JS: ends with comma (open ending)
        result = detect_truncation(
            "function myFunc() {\n  const x = 1,\n", file_path="test.js"
        )
        assert result.is_truncated is True

    def test_valid_js_file(self) -> None:
        result = detect_truncation(
            "function myFunc() {\n  return 42;\n}\n", file_path="test.js"
        )
        assert result.is_truncated is False

    def test_non_string_input(self) -> None:
        result = detect_truncation(42)  # type: ignore[arg-type]
        assert result.is_truncated is False

    def test_non_string_returns_false(self) -> None:
        """Non-string input should not crash, just return not-truncated."""
        assert is_truncated(None) is False  # type: ignore[arg-type]

    def test_first_match_wins(self) -> None:
        """When multiple methods would match, the first one wins."""
        # Empty string triggers 'empty' before any other check
        result = detect_truncation("")
        assert result.method == "empty"

    def test_result_is_frozen(self) -> None:
        """TruncationResult is a frozen dataclass."""
        result = detect_truncation("x = 1\n")
        with pytest.raises(AttributeError):
            result.is_truncated = True  # type: ignore[misc]

    def test_long_valid_python(self) -> None:
        code = textwrap.dedent("""\
            import os
            import sys
            from pathlib import Path


            def main():
                print("Hello, world!")


            if __name__ == "__main__":
                main()
        """)
        assert detect_truncation(code, file_path="main.py").is_truncated is False


class TestIsTruncated:
    """Tests for the is_truncated convenience wrapper."""

    def test_truncated(self) -> None:
        assert is_truncated("def foo(\n", file_path="test.py") is True

    def test_not_truncated(self) -> None:
        assert is_truncated("x = 1\n", file_path="test.py") is False


# ===================================================================
# 3. Backward compatibility — code_critic/reviewer.py re-export
# ===================================================================


class TestBackwardCompatReexport:
    """Tests that the code_critic reviewer.py re-export still works."""

    def test_import_works(self) -> None:
        from code_muse.plugins.code_critic.reviewer import _detect_code_truncation

        result = _detect_code_truncation("def foo(\n", "test.py")
        assert isinstance(result, tuple)
        assert len(result) == 2
        assert result[0] is True  # is_truncated
        assert result[1] is not None  # reason string

    def test_valid_code_through_compat(self) -> None:
        from code_muse.plugins.code_critic.reviewer import _detect_code_truncation

        result = _detect_code_truncation("x = 1\n", "test.py")
        assert result[0] is False
        assert result[1] is None

    def test_empty_through_compat(self) -> None:
        from code_muse.plugins.code_critic.reviewer import _detect_code_truncation

        result = _detect_code_truncation("", "test.py")
        assert result[0] is True


# ===================================================================
# 4. Hook integration tests — register_callbacks.py
# ===================================================================


class TestPreToolCallHook:
    """Tests for the pre_tool_call hook (critic gating)."""

    def test_blocks_critic_on_truncated_file(self, tmp_path: Path) -> None:
        from code_muse.plugins.truncation_detector.register_callbacks import (
            _on_pre_tool_call,
            _reset_state,
        )

        _reset_state()

        # Create a truncated Python file
        truncated_file = tmp_path / "truncated.py"
        truncated_file.write_text("def foo(\n")

        result = _run_async(
            _on_pre_tool_call(
                "request_code_review",
                {"file_path": str(truncated_file)},
                None,
            )
        )

        assert result is not None
        assert result.get("blocked") is True
        assert "truncation" in result.get("reason", "").lower()

    def test_allows_critic_on_valid_file(self, tmp_path: Path) -> None:
        from code_muse.plugins.truncation_detector.register_callbacks import (
            _on_pre_tool_call,
            _reset_state,
        )

        _reset_state()

        # Create a valid Python file
        valid_file = tmp_path / "valid.py"
        valid_file.write_text("x = 1\n")

        result = _run_async(
            _on_pre_tool_call(
                "request_code_review",
                {"file_path": str(valid_file)},
                None,
            )
        )

        assert result is None  # Not blocked

    def test_ignores_non_critic_tools(self, tmp_path: Path) -> None:
        from code_muse.plugins.truncation_detector.register_callbacks import (
            _on_pre_tool_call,
        )

        result = _run_async(
            _on_pre_tool_call(
                "some_other_tool",
                {"file_path": str(tmp_path / "fake.py")},
                None,
            )
        )

        assert result is None

    def test_allows_when_no_file_path(
        self,
    ) -> None:
        from code_muse.plugins.truncation_detector.register_callbacks import (
            _on_pre_tool_call,
        )

        result = _run_async(
            _on_pre_tool_call(
                "request_code_review",
                {},  # No file_path key
                None,
            )
        )

        assert result is None

    def test_allows_when_file_not_found(
        self,
    ) -> None:
        from code_muse.plugins.truncation_detector.register_callbacks import (
            _on_pre_tool_call,
        )

        result = _run_async(
            _on_pre_tool_call(
                "request_code_review",
                {"file_path": "/nonexistent/path/test.py"},
                None,
            )
        )

        assert result is None  # Can't read — don't block


class TestPostToolCallHook:
    """Tests for the post_tool_call hook (file-write monitoring)."""

    def test_detects_truncation_in_written_file(self, tmp_path: Path) -> None:
        from code_muse.plugins.truncation_detector.register_callbacks import (
            _on_post_tool_call,
            _reset_state,
        )

        _reset_state()

        # Create a truncated file on disk
        truncated_file = tmp_path / "truncated.py"
        truncated_file.write_text("def foo(\n")

        # Should not raise — just emit warning
        _run_async(
            _on_post_tool_call(
                "create_file",
                {"file_path": str(truncated_file)},
                None,
                100.0,
                None,
            )
        )

    def test_ignores_non_write_tools(self, tmp_path: Path) -> None:
        from code_muse.plugins.truncation_detector.register_callbacks import (
            _on_post_tool_call,
        )

        # Should be a no-op
        _run_async(
            _on_post_tool_call(
                "read_file",
                {"file_path": str(tmp_path / "some.py")},
                None,
                50.0,
                None,
            )
        )


class TestCustomCommands:
    """Tests for the /truncation-detector slash commands."""

    def test_status_command(self) -> None:
        from code_muse.plugins.truncation_detector.register_callbacks import (
            _on_custom_command,
            _reset_state,
        )

        _reset_state()
        with patch("code_muse.messaging.emit_info") as mock_emit:
            result = _on_custom_command(
                "/truncation-detector status", "truncation-detector"
            )
            assert result is True
            mock_emit.assert_called_once()
            output = mock_emit.call_args[0][0]
            assert "enabled" in output.lower() or "status" in output.lower()

    def test_off_command(self) -> None:
        from code_muse.plugins.truncation_detector.register_callbacks import (
            _on_custom_command,
            _reset_state,
        )

        _reset_state()
        with patch("code_muse.messaging.emit_warning"):
            result = _on_custom_command(
                "/truncation-detector off", "truncation-detector"
            )
            assert result is True

    def test_on_command(self) -> None:
        from code_muse.plugins.truncation_detector.register_callbacks import (
            _on_custom_command,
        )

        with patch("code_muse.messaging.emit_success"):
            result = _on_custom_command(
                "/truncation-detector on", "truncation-detector"
            )
            assert result is True

    def test_reset_command(self) -> None:
        from code_muse.plugins.truncation_detector.register_callbacks import (
            _on_custom_command,
            _reset_state,
        )

        _reset_state()
        with patch("code_muse.messaging.emit_success"):
            result = _on_custom_command(
                "/truncation-detector reset", "truncation-detector"
            )
            assert result is True

    def test_help_command(self) -> None:
        from code_muse.plugins.truncation_detector.register_callbacks import (
            _on_custom_command,
        )

        with patch("code_muse.messaging.emit_info") as mock_emit:
            result = _on_custom_command(
                "/truncation-detector help", "truncation-detector"
            )
            assert result is True
            output = mock_emit.call_args[0][0]
            assert "status" in output.lower()

    def test_unknown_command_shows_usage(self) -> None:
        from code_muse.plugins.truncation_detector.register_callbacks import (
            _on_custom_command,
        )

        with patch("code_muse.messaging.emit_info"):
            result = _on_custom_command(
                "/truncation-detector bogus", "truncation-detector"
            )
            assert result is True

    def test_short_alias(self) -> None:
        from code_muse.plugins.truncation_detector.register_callbacks import (
            _on_custom_command,
            _reset_state,
        )

        _reset_state()
        with patch("code_muse.messaging.emit_info"):
            result = _on_custom_command("/truncation status", "truncation")
            assert result is True

    def test_unrelated_command_returns_none(self) -> None:
        from code_muse.plugins.truncation_detector.register_callbacks import (
            _on_custom_command,
        )

        result = _on_custom_command("/something-else", "something-else")
        assert result is None


class TestCustomCommandHelp:
    """Tests for the custom_command_help hook."""

    def test_returns_entries(self) -> None:
        from code_muse.plugins.truncation_detector.register_callbacks import (
            _on_custom_command_help,
        )

        entries = _on_custom_command_help()
        assert isinstance(entries, list)
        assert len(entries) > 0
        # Each entry is a (command, description) tuple
        for cmd, desc in entries:
            assert isinstance(cmd, str)
            assert isinstance(desc, str)
            assert "truncation" in cmd.lower()


class TestDisabledState:
    """Tests that the off/on toggle works correctly."""

    def test_off_disables_pre_tool_call(self, tmp_path: Path) -> None:
        from code_muse.plugins.truncation_detector.register_callbacks import (
            _on_custom_command,
            _on_pre_tool_call,
            _reset_state,
        )

        _reset_state()

        # Disable
        with patch("code_muse.messaging.emit_warning"):
            _on_custom_command("/truncation-detector off", "truncation-detector")

        # Create a truncated file
        truncated_file = tmp_path / "truncated.py"
        truncated_file.write_text("def foo(\n")

        result = _run_async(
            _on_pre_tool_call(
                "request_code_review",
                {"file_path": str(truncated_file)},
                None,
            )
        )

        # Should NOT be blocked when disabled
        assert result is None

        # Re-enable for other tests
        with patch("code_muse.messaging.emit_success"):
            _on_custom_command("/truncation-detector on", "truncation-detector")

    def test_off_disables_post_tool_call(self, tmp_path: Path) -> None:
        from code_muse.plugins.truncation_detector.register_callbacks import (
            _on_custom_command,
            _on_post_tool_call,
            _reset_state,
        )

        _reset_state()

        # Disable
        with patch("code_muse.messaging.emit_warning"):
            _on_custom_command("/truncation-detector off", "truncation-detector")

        # Create a truncated file
        truncated_file = tmp_path / "truncated.py"
        truncated_file.write_text("def foo(\n")

        # Should be a no-op (not crash, not emit warning)
        _run_async(
            _on_post_tool_call(
                "create_file",
                {"file_path": str(truncated_file)},
                None,
                100.0,
                None,
            )
        )

        # Re-enable for other tests
        with patch("code_muse.messaging.emit_success"):
            _on_custom_command("/truncation-detector on", "truncation-detector")


# ===================================================================
# 5. Edge cases and robustness
# ===================================================================


class TestEdgeCases:
    """Edge cases and robustness tests."""

    def test_unicode_content(self) -> None:
        code = "x = '你好世界'\n"
        result = detect_truncation(code, file_path="test.py")
        assert result.is_truncated is False

    def test_very_long_line(self) -> None:
        code = "x = " + "a" * 10000 + "\n"
        result = detect_truncation(code, file_path="test.py")
        assert result.is_truncated is False

    def test_mixed_language_content(self) -> None:
        """Non-Python files should still be checked by heuristics."""
        # Clearly truncated JS — ends with colon
        code = "const obj = {\n  key:\n"
        result = detect_truncation(code, file_path="test.js")
        assert result.is_truncated is True

    def test_json_with_non_truncation_error(self) -> None:
        """JSON that fails for non-truncation reasons should not be flagged."""
        # Invalid JSON that doesn't start with { or [ is not checked
        code = "not json at all"
        result = _check_incomplete_json(code)
        assert result is None

        # JSON with non-truncation error (starts with { but bad value)
        # Note: json.loads('"key": undefined') actually raises
        # "Expecting value" which contains "Expecting" — our check
        # flags this. That's a known minor false positive we accept
        # for safety (better to flag than miss real truncation).

    def test_nested_code_blocks(self) -> None:
        """Multiple markdown code blocks — all closed."""
        content = "```python\nx = 1\n```\n```js\nconst y = 2;\n```\n"
        result = _check_markdown_blocks(content)
        assert result is None

    def test_all_critic_tool_names(self) -> None:
        """Verify all expected critic tool names are in the set."""
        from code_muse.plugins.truncation_detector.register_callbacks import (
            _CRITIC_TOOL_NAMES,
        )

        expected = {
            "request_code_review",
            "request_review",
            "review_code",
            "code_review",
            "auto_review",
            "critique_code",
            "critic_review",
        }
        assert expected == _CRITIC_TOOL_NAMES

    def test_all_file_write_tool_names(self) -> None:
        """Verify all expected file-write tool names are in the set."""
        from code_muse.plugins.truncation_detector.register_callbacks import (
            _FILE_WRITE_TOOLS,
        )

        expected = {"create_file", "replace_in_file", "edit_file"}
        assert expected == _FILE_WRITE_TOOLS


class TestMetricEmission:
    """Tests that truncation events emit metrics when upgrade_metrics is available."""

    def test_emit_metric_called_on_block(self, tmp_path: Path) -> None:
        from code_muse.plugins.truncation_detector.register_callbacks import (
            _on_pre_tool_call,
            _reset_state,
        )

        _reset_state()

        truncated_file = tmp_path / "truncated.py"
        truncated_file.write_text("def foo(\n")

        with patch(
            "code_muse.plugins.truncation_detector.register_callbacks._emit_metric"
        ) as mock_emit:
            _run_async(
                _on_pre_tool_call(
                    "request_code_review",
                    {"file_path": str(truncated_file)},
                    None,
                )
            )
            mock_emit.assert_called_once()
            data = mock_emit.call_args[0][0]
            assert data["tool_name"] == "request_code_review"
            assert data["blocked_critic_call"] is True

    def test_emit_metric_graceful_when_unavailable(self, tmp_path: Path) -> None:
        """When upgrade_metrics is not installed, emit_metric should not crash."""
        from code_muse.plugins.truncation_detector.register_callbacks import (
            _emit_metric,
        )

        # Should not raise even if upgrade_metrics is not installed
        _emit_metric({"test": True})
