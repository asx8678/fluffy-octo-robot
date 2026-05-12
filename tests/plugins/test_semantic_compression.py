"""Tests for the semantic_compression plugin config and gating."""

import pytest

from code_muse.plugins.semantic_compression.config import (
    get_compression_allowlist,
    get_compression_blocklist,
    get_semantic_compression_enabled,
    is_tool_allowed,
    set_compression_allowlist,
    set_compression_blocklist,
    set_semantic_compression_enabled,
)
from code_muse.plugins.semantic_compression.register_callbacks import (
    _handle_semantic_compression_command,
    _on_post_tool_call,
    _show_semantic_compression_status,
)

# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------


class TestSemanticCompressionConfig:
    """Unit tests for the plugin-level config helpers."""

    def test_default_enabled_is_false(self):
        assert get_semantic_compression_enabled() is False

    def test_enable_and_disable(self):
        set_semantic_compression_enabled(True)
        assert get_semantic_compression_enabled() is True

        set_semantic_compression_enabled(False)
        assert get_semantic_compression_enabled() is False

    def test_allowlist_default_empty(self):
        assert get_compression_allowlist() == set()

    def test_allowlist_round_trip(self):
        tools = {"read_file", "grep", "list_files"}
        set_compression_allowlist(tools)
        assert get_compression_allowlist() == tools

        set_compression_allowlist(set())
        assert get_compression_allowlist() == set()

    def test_blocklist_default_empty(self):
        assert get_compression_blocklist() == set()

    def test_blocklist_round_trip(self):
        tools = {"run_shell_command", "agent_run_shell_command"}
        set_compression_blocklist(tools)
        assert get_compression_blocklist() == tools

        set_compression_blocklist(set())
        assert get_compression_blocklist() == set()

    def test_is_tool_allowed_no_lists(self):
        """When both lists are empty, every tool is allowed."""
        set_compression_allowlist(set())
        set_compression_blocklist(set())
        assert is_tool_allowed("read_file") is True
        assert is_tool_allowed("grep") is True

    def test_is_tool_allowed_with_blocklist(self):
        set_compression_blocklist({"run_shell_command"})
        assert is_tool_allowed("run_shell_command") is False
        assert is_tool_allowed("read_file") is True

    def test_is_tool_allowed_with_allowlist(self):
        set_compression_allowlist({"read_file", "grep"})
        assert is_tool_allowed("read_file") is True
        assert is_tool_allowed("grep") is True
        assert is_tool_allowed("list_files") is False

    def test_is_tool_allowed_both_lists(self):
        """Blocklist wins over allowlist."""
        set_compression_allowlist({"read_file", "grep", "run_shell_command"})
        set_compression_blocklist({"run_shell_command"})
        assert is_tool_allowed("read_file") is True
        assert is_tool_allowed("grep") is True
        assert is_tool_allowed("run_shell_command") is False
        assert is_tool_allowed("list_files") is False


# ---------------------------------------------------------------------------
# post_tool_call gating
# ---------------------------------------------------------------------------


class TestPostToolCallGating:
    """Unit tests for the gated post_tool_call callback."""

    @pytest.fixture(autouse=True)
    def _reset_config(self):
        """Reset config to defaults before each test."""
        set_semantic_compression_enabled(False)
        set_compression_allowlist(set())
        set_compression_blocklist(set())

    @pytest.mark.asyncio
    async def test_disabled_returns_none(self):
        set_semantic_compression_enabled(False)
        result = await _on_post_tool_call("read_file", {}, "a" * 500, 1.0, None)
        assert result is None

    @pytest.mark.asyncio
    async def test_blocklist_returns_none(self):
        set_semantic_compression_enabled(True)
        set_compression_blocklist({"read_file"})
        result = await _on_post_tool_call("read_file", {}, "a" * 500, 1.0, None)
        assert result is None

    @pytest.mark.asyncio
    async def test_allowlist_excludes_returns_none(self):
        set_semantic_compression_enabled(True)
        set_compression_allowlist({"grep"})
        result = await _on_post_tool_call("read_file", {}, "a" * 500, 1.0, None)
        assert result is None

    @pytest.mark.asyncio
    async def test_enabled_and_allowed_compresses(self):
        set_semantic_compression_enabled(True)
        text = (
            "This is a very long sentence that has many words in it. "
            "The quick brown fox jumps over the lazy dog. "
            "We need to make sure that this text is longer than the minimum threshold "
            "so that the semantic compression callback actually processes it rather than "
            "skipping due to the short length check. Here are some more filler words."
        )
        assert len(text) > 200
        result = await _on_post_tool_call("read_file", {}, text, 1.0, None)
        assert result is not None
        assert len(result) < len(text)

    @pytest.mark.asyncio
    async def test_short_result_returns_none_even_when_enabled(self):
        set_semantic_compression_enabled(True)
        result = await _on_post_tool_call("read_file", {}, "short", 1.0, None)
        assert result is None

    @pytest.mark.asyncio
    async def test_non_string_result_returns_none(self):
        set_semantic_compression_enabled(True)
        result = await _on_post_tool_call("read_file", {}, {"key": "value"}, 1.0, None)
        assert result is None


# ---------------------------------------------------------------------------
# Slash command handler
# ---------------------------------------------------------------------------


class TestSemanticCompressionCommand:
    """Unit tests for the /semantic-compression slash command."""

    @pytest.fixture(autouse=True)
    def _reset_config(self):
        set_semantic_compression_enabled(False)
        set_compression_allowlist(set())
        set_compression_blocklist(set())

    def test_returns_none_for_wrong_name(self):
        assert _handle_semantic_compression_command("/other", "other") is None

    def test_status_bare_command(self):
        result = _handle_semantic_compression_command(
            "/semantic-compression", "semantic-compression"
        )
        assert isinstance(result, str)
        assert "Enabled: no" in result

    def test_turn_on(self):
        result = _handle_semantic_compression_command(
            "/semantic-compression on", "semantic-compression"
        )
        assert result is True
        assert get_semantic_compression_enabled() is True

    def test_turn_off(self):
        set_semantic_compression_enabled(True)
        result = _handle_semantic_compression_command(
            "/semantic-compression off", "semantic-compression"
        )
        assert result is True
        assert get_semantic_compression_enabled() is False

    def test_allowlist_set(self):
        result = _handle_semantic_compression_command(
            "/semantic-compression allowlist read_file, grep", "semantic-compression"
        )
        assert result is True
        assert get_compression_allowlist() == {"read_file", "grep"}

    def test_allowlist_clear(self):
        set_compression_allowlist({"read_file"})
        result = _handle_semantic_compression_command(
            "/semantic-compression allowlist", "semantic-compression"
        )
        assert result is True
        assert get_compression_allowlist() == set()

    def test_blocklist_set(self):
        result = _handle_semantic_compression_command(
            "/semantic-compression blocklist run_shell_command", "semantic-compression"
        )
        assert result is True
        assert get_compression_blocklist() == {"run_shell_command"}

    def test_blocklist_clear(self):
        set_compression_blocklist({"run_shell_command"})
        result = _handle_semantic_compression_command(
            "/semantic-compression blocklist", "semantic-compression"
        )
        assert result is True
        assert get_compression_blocklist() == set()

    def test_unknown_subcommand_returns_true_with_error(self):
        result = _handle_semantic_compression_command(
            "/semantic-compression foobar", "semantic-compression"
        )
        assert result is True


# ---------------------------------------------------------------------------
# Status display
# ---------------------------------------------------------------------------


class TestShowStatus:
    def test_status_output(self):
        set_semantic_compression_enabled(False)
        set_compression_allowlist(set())
        set_compression_blocklist(set())
        status = _show_semantic_compression_status()
        assert "Enabled: no" in status
        assert "Allowlist: (none" in status
        assert "Blocklist: (none)" in status

    def test_status_with_lists(self):
        set_semantic_compression_enabled(True)
        set_compression_allowlist({"read_file"})
        set_compression_blocklist({"run_shell_command"})
        status = _show_semantic_compression_status()
        assert "Enabled: yes" in status
        assert "read_file" in status
        assert "run_shell_command" in status
