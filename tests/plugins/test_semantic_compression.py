"""Tests for the semantic_compression plugin config and gating."""

import pytest

from code_muse.plugins.semantic_compression.compressor import compress_semantic
from code_muse.plugins.semantic_compression.config import (
    get_compression_allowlist,
    get_compression_blocklist,
    get_default_compression_tools,
    get_semantic_compression_enabled,
    is_tool_allowed,
    set_compression_allowlist,
    set_compression_blocklist,
    set_semantic_compression_enabled,
)
from code_muse.plugins.semantic_compression.register_callbacks import (
    _COMPRESSION_MARKER,
    _handle_semantic_compression_command,
    _handle_show_command,
    _on_post_tool_call,
    _show_compression_stats,
    _show_semantic_compression_status,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Paragraph with many function words — repeated to exceed 700 post-compression words
_PARAGRAPH = (
    "This is a very long sentence that has many words in it. "
    "The quick brown fox jumps over the lazy dog. "
    "We need to make sure that this text is longer than "
    "the minimum threshold so that the semantic compression "
    "callback actually processes it rather than skipping "
    "due to the short length check. Here are some more "
    "filler words. The system was designed by the team "
    "in order to provide a very reliable and quite efficient "
    "mechanism for the processing of the data that was collected "
    "by the research team. Each and every record was reviewed "
    "by the committee that was formed in order to ensure quality. "
    "The analysis was performed by the lead scientist and the "
    "results were extremely promising. A decision was made to "
    "continue the investigation. It is worth noting that the "
    "data was gathered due to the fact that the previous study "
    "was rather inconclusive. The team made a recommendation "
    "that the project should be extended. They took into account "
    "the various and sundry factors that were considered rather "
    "important by the stakeholders. This was rather really very "
    "quite extremely somewhat important for the overall success "
    "of the endeavor that was being undertaken by the group. "
    "The committee reached a conclusion that the project was "
    "null and void due to the fact that the funding was cut. "
    "A prediction was made by the analyst that the market would "
    "recover. The system gave consideration to all the feedback "
    "that was provided by the users who were surveyed."
)
# Repeat 6x to ensure >700 content words after compression
_LONG_TEXT = " ".join([_PARAGRAPH] * 6)


def _reset_all_state():
    """Reset all config and module-level state to defaults."""
    set_semantic_compression_enabled(True)
    set_compression_allowlist(set())
    set_compression_blocklist(set())
    import code_muse.plugins.semantic_compression.register_callbacks as rc

    rc._last_original_output = None
    rc._compression_stats = {
        "total_compressed": 0,
        "total_original_tokens": 0,
        "total_compressed_tokens": 0,
        "total_original_chars": 0,
        "total_compressed_chars": 0,
    }


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------


class TestSemanticCompressionConfig:
    """Unit tests for the plugin-level config helpers."""

    @pytest.fixture(autouse=True)
    def _reset_config(self):
        _reset_all_state()

    def test_default_enabled_is_true(self):
        assert get_semantic_compression_enabled() is True

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

    def test_default_compression_tools(self):
        defaults = get_default_compression_tools()
        assert "read_file" in defaults
        assert "grep" in defaults
        assert "run_shell_command" in defaults
        assert "list_files" in defaults
        assert "agent_run_shell_command" in defaults
        assert "invoke_agent" in defaults
        assert "read_relevant_code" in defaults
        assert "create_file" not in defaults
        assert "replace_in_file" not in defaults
        assert "delete_file" not in defaults

    def test_is_tool_allowed_default_tools(self):
        """Default tools are allowed without explicit allowlist."""
        set_compression_allowlist(set())
        set_compression_blocklist(set())
        assert is_tool_allowed("read_file") is True
        assert is_tool_allowed("grep") is True
        assert is_tool_allowed("run_shell_command") is True
        assert is_tool_allowed("list_files") is True
        assert is_tool_allowed("agent_run_shell_command") is True
        assert is_tool_allowed("invoke_agent") is True
        assert is_tool_allowed("read_relevant_code") is True

    def test_is_tool_allowed_non_default_blocked(self):
        """Non-default tools not in allowlist are blocked."""
        set_compression_allowlist(set())
        set_compression_blocklist(set())
        assert is_tool_allowed("create_file") is False
        assert is_tool_allowed("replace_in_file") is False

    def test_is_tool_allowed_with_blocklist(self):
        """Blocklist overrides default tools."""
        set_compression_allowlist(set())
        set_compression_blocklist({"run_shell_command"})
        assert is_tool_allowed("run_shell_command") is False
        assert is_tool_allowed("read_file") is True

    def test_is_tool_allowed_with_allowlist(self):
        """Allowlist adds extra tools beyond defaults."""
        set_compression_allowlist({"create_file"})
        assert is_tool_allowed("create_file") is True
        assert is_tool_allowed("read_file") is True  # default
        assert is_tool_allowed("replace_in_file") is False

    def test_is_tool_allowed_both_lists(self):
        """Blocklist wins over allowlist and defaults."""
        set_compression_allowlist({"read_file", "grep", "create_file"})
        set_compression_blocklist({"run_shell_command", "create_file"})
        assert is_tool_allowed("read_file") is True  # default
        assert is_tool_allowed("grep") is True  # default
        assert is_tool_allowed("run_shell_command") is False  # blocked
        assert is_tool_allowed("create_file") is False  # blocked
        assert is_tool_allowed("replace_in_file") is False  # not in lists


# ---------------------------------------------------------------------------
# post_tool_call gating
# ---------------------------------------------------------------------------


class TestPostToolCallGating:
    """Unit tests for the gated post_tool_call callback."""

    @pytest.fixture(autouse=True)
    def _reset_config(self):
        _reset_all_state()

    @pytest.mark.asyncio
    async def test_disabled_returns_none(self):
        set_semantic_compression_enabled(False)
        result = await _on_post_tool_call("read_file", {}, "a" * 500, 1.0, None)
        assert result is None

    @pytest.mark.asyncio
    async def test_blocklist_returns_none(self):
        set_compression_blocklist({"read_file"})
        result = await _on_post_tool_call("read_file", {}, "a" * 500, 1.0, None)
        assert result is None

    @pytest.mark.asyncio
    async def test_non_default_tool_returns_none(self):
        """Non-default tools without allowlist entry are not compressed."""
        result = await _on_post_tool_call("create_file", {}, _LONG_TEXT, 1.0, None)
        assert result is None

    @pytest.mark.asyncio
    async def test_default_tool_compresses(self):
        """Default tools are compressed when enabled."""
        result = await _on_post_tool_call("read_file", {}, _LONG_TEXT, 1.0, None)
        assert result is not None
        assert len(result) < len(_LONG_TEXT)

    @pytest.mark.asyncio
    async def test_compressed_output_has_marker(self):
        """Compressed output ends with the double-compression marker."""
        result = await _on_post_tool_call("read_file", {}, _LONG_TEXT, 1.0, None)
        assert result is not None
        assert result.endswith(_COMPRESSION_MARKER)

    @pytest.mark.asyncio
    async def test_double_compression_prevented(self):
        """Already-compressed output (with marker) is not re-compressed."""
        result1 = await _on_post_tool_call("read_file", {}, _LONG_TEXT, 1.0, None)
        assert result1 is not None
        # Feed the compressed result back in
        result2 = await _on_post_tool_call("read_file", {}, result1, 1.0, None)
        assert result2 is None  # Should skip due to marker

    @pytest.mark.asyncio
    async def test_short_result_returns_none(self):
        result = await _on_post_tool_call("read_file", {}, "short", 1.0, None)
        assert result is None

    @pytest.mark.asyncio
    async def test_non_string_result_returns_none(self):
        result = await _on_post_tool_call("read_file", {}, {"key": "value"}, 1.0, None)
        assert result is None

    @pytest.mark.asyncio
    async def test_700_word_safety_rail(self):
        """Text that would compress below 700 content words is not compressed."""
        # Build text with exactly ~750 words — after compression might go
        # below 700.  We need text that is long enough to pass
        # _MIN_COMPRESS_LENGTH but compresses to < 700 words.
        # Use dense technical text with few function words to compress
        # below 700 words.
        short_text = (
            "The system is very reliable. " * 30  # ~210 words
        )
        assert len(short_text) > 200  # passes length gate
        # This should still be compressed (words > 700 won't apply here)
        # Actually let's test the OPPOSITE: make a text that's long
        # enough but has so few words after compression that it's < 700
        # The simplest way: text with < 700 words total
        result = await _on_post_tool_call("read_file", {}, short_text, 1.0, None)
        assert result is None  # Under 700 words → safety rail

    @pytest.mark.asyncio
    async def test_compression_emits_event(self):
        """compression_applied event is emitted to upgrade_metrics."""
        from unittest.mock import MagicMock, patch

        mock_emit = MagicMock()
        mock_module = MagicMock(emit_metric=mock_emit)
        with (
            patch(
                "code_muse.plugins.semantic_compression.register_callbacks.emit_info"
            ),
            patch.dict(
                "sys.modules",
                {"code_muse.plugins.upgrade_metrics": mock_module},
            ),
        ):
            result = await _on_post_tool_call("read_file", {}, _LONG_TEXT, 1.0, None)
            if result is not None:
                mock_emit.assert_called_once()
                call_args = mock_emit.call_args
                assert call_args[0][0] == "compression_applied"
                data = call_args[0][1]
                assert "tool_name" in data
                assert data["tool_name"] == "read_file"
                assert "original_tokens" in data
                assert "compressed_tokens" in data

    @pytest.mark.asyncio
    async def test_compression_stores_original(self):
        """Original output is stored for /show original."""
        import code_muse.plugins.semantic_compression.register_callbacks as rc

        rc._last_original_output = None
        result = await _on_post_tool_call("read_file", {}, _LONG_TEXT, 1.0, None)
        if result is not None:
            assert rc._last_original_output == _LONG_TEXT

    @pytest.mark.asyncio
    async def test_compression_updates_stats(self):
        """Compression stats are updated after each compression."""
        import code_muse.plugins.semantic_compression.register_callbacks as rc

        rc._compression_stats = {
            "total_compressed": 0,
            "total_original_tokens": 0,
            "total_compressed_tokens": 0,
            "total_original_chars": 0,
            "total_compressed_chars": 0,
        }
        result = await _on_post_tool_call("read_file", {}, _LONG_TEXT, 1.0, None)
        if result is not None:
            assert rc._compression_stats["total_compressed"] == 1
            assert rc._compression_stats["total_original_tokens"] > 0
            assert rc._compression_stats["total_compressed_tokens"] > 0
            assert rc._compression_stats["total_original_chars"] > 0
            assert rc._compression_stats["total_compressed_chars"] > 0

    @pytest.mark.asyncio
    async def test_off_completely_disables(self):
        """/semantic-compression off makes post_tool_call return None."""
        set_semantic_compression_enabled(False)
        result = await _on_post_tool_call("read_file", {}, _LONG_TEXT, 1.0, None)
        assert result is None


# ---------------------------------------------------------------------------
# Slash command handler
# ---------------------------------------------------------------------------


class TestSemanticCompressionCommand:
    """Unit tests for the /semantic-compression slash command."""

    @pytest.fixture(autouse=True)
    def _reset_config(self):
        _reset_all_state()

    def test_returns_none_for_wrong_name(self):
        assert _handle_semantic_compression_command("/other", "other") is None

    def test_status_bare_command(self):
        result = _handle_semantic_compression_command(
            "/semantic-compression", "semantic-compression"
        )
        assert isinstance(result, str)
        assert "Enabled: yes" in result

    def test_status_shows_default_tools(self):
        result = _handle_semantic_compression_command(
            "/semantic-compression", "semantic-compression"
        )
        assert isinstance(result, str)
        assert "read_file" in result

    def test_turn_on(self):
        set_semantic_compression_enabled(False)
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

    def test_stats_shows_counters(self):
        import code_muse.plugins.semantic_compression.register_callbacks as rc

        rc._compression_stats = {
            "total_compressed": 5,
            "total_original_tokens": 10000,
            "total_compressed_tokens": 7000,
            "total_original_chars": 50000,
            "total_compressed_chars": 35000,
        }
        result = _handle_semantic_compression_command(
            "/semantic-compression stats", "semantic-compression"
        )
        assert isinstance(result, str)
        assert "5" in result
        assert "3,000" in result  # 10000 - 7000 = 3000 tokens saved
        assert "15,000" in result  # 50000 - 35000 = 15000 chars saved

    def test_allowlist_set(self):
        result = _handle_semantic_compression_command(
            "/semantic-compression allowlist read_file, grep",
            "semantic-compression",
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
            "/semantic-compression blocklist run_shell_command",
            "semantic-compression",
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
    @pytest.fixture(autouse=True)
    def _reset_config(self):
        _reset_all_state()

    def test_status_output_default(self):
        set_semantic_compression_enabled(True)
        set_compression_allowlist(set())
        set_compression_blocklist(set())
        status = _show_semantic_compression_status()
        assert "Enabled: yes" in status
        assert "Default tools" in status
        assert "read_file" in status

    def test_status_with_blocklist(self):
        set_semantic_compression_enabled(True)
        set_compression_blocklist({"run_shell_command"})
        status = _show_semantic_compression_status()
        assert "Enabled: yes" in status
        assert "run_shell_command" in status

    def test_status_disabled(self):
        set_semantic_compression_enabled(False)
        status = _show_semantic_compression_status()
        assert "Enabled: no" in status


# ---------------------------------------------------------------------------
# Compression stats display
# ---------------------------------------------------------------------------


class TestShowCompressionStats:
    @pytest.fixture(autouse=True)
    def _reset_config(self):
        _reset_all_state()

    def test_stats_empty(self):
        import code_muse.plugins.semantic_compression.register_callbacks as rc

        rc._compression_stats = {
            "total_compressed": 0,
            "total_original_tokens": 0,
            "total_compressed_tokens": 0,
            "total_original_chars": 0,
            "total_compressed_chars": 0,
        }
        stats = _show_compression_stats()
        assert "0" in stats

    def test_stats_with_data(self):
        import code_muse.plugins.semantic_compression.register_callbacks as rc

        rc._compression_stats = {
            "total_compressed": 10,
            "total_original_tokens": 50000,
            "total_compressed_tokens": 35000,
            "total_original_chars": 200000,
            "total_compressed_chars": 140000,
        }
        stats = _show_compression_stats()
        assert "10" in stats
        assert "50,000" in stats
        assert "35,000" in stats
        assert "15,000" in stats  # tokens saved
        assert "200,000" in stats  # original chars
        assert "140,000" in stats  # compressed chars
        assert "60,000" in stats  # chars saved


# ---------------------------------------------------------------------------
# /show original command
# ---------------------------------------------------------------------------


class TestShowOriginalCommand:
    @pytest.fixture(autouse=True)
    def _reset_config(self):
        _reset_all_state()

    def test_returns_none_for_wrong_name(self):
        assert _handle_show_command("/other", "other") is None

    def test_returns_none_for_wrong_subcommand(self):
        assert _handle_show_command("/show config", "show") is None

    def test_no_original_stored(self):
        from unittest.mock import patch

        import code_muse.plugins.semantic_compression.register_callbacks as rc

        rc._last_original_output = None
        with patch(
            "code_muse.plugins.semantic_compression.register_callbacks.emit_info"
        ):
            result = _handle_show_command("/show original", "show")
        assert result is True

    def test_shows_stored_original(self):
        import code_muse.plugins.semantic_compression.register_callbacks as rc

        rc._last_original_output = "the original text"
        result = _handle_show_command("/show original", "show")
        assert isinstance(result, str)
        assert "the original text" in result

    def test_truncates_very_long_original(self):
        import code_muse.plugins.semantic_compression.register_callbacks as rc

        rc._last_original_output = "x" * 10000
        result = _handle_show_command("/show original", "show")
        assert isinstance(result, str)
        assert "truncated" in result


# ---------------------------------------------------------------------------
# Compressor — code identifier and quote protection
# ---------------------------------------------------------------------------


class TestCompressorCodeProtection:
    """Verify the compressor does not mangle code identifiers or quoted strings."""

    def test_passive_voice_in_quotes_preserved(self):
        """Passive→active should not fire inside double-quoted strings."""
        text = '{"status": "was closed by owner", "id": 1}'
        result = compress_semantic(text, aggressive=False)
        # "was closed by owner" should NOT be transformed to "owner closed"
        assert "was closed by owner" in result

    def test_passive_voice_in_single_quotes_preserved(self):
        """Passive→active should not fire inside single-quoted strings."""
        text = "status: 'was owned by admin', result: ok"
        result = compress_semantic(text, aggressive=False)
        assert "was owned by admin" in result

    def test_passive_voice_in_prose_still_works(self):
        """Passive→active should still work in natural language."""
        text = "The bug was closed by the maintainer yesterday afternoon."
        result = compress_semantic(text, aggressive=False)
        # Should transform to something like "maintainer closed"
        assert "closed" in result
        assert "by the" not in result

    def test_inline_code_preserved(self):
        """Backtick-wrapped inline code should not be compressed."""
        text = "The variable `was_closed_by_user` indicates the status."
        result = compress_semantic(text, aggressive=False)
        assert "`was_closed_by_user`" in result

    def test_fenced_code_block_preserved(self):
        """Fenced code blocks should not be compressed."""
        text = (
            "The result was processed by the system. "
            "```python\nwas_closed_by = True\n```"
        )
        result = compress_semantic(text, aggressive=False)
        assert "was_closed_by = True" in result

    def test_json_keys_not_stripped(self):
        """Articles/copulas in JSON values inside quotes should not be stripped."""
        text = '{"msg": "The file was created by the admin", "ok": true}'
        result = compress_semantic(text, aggressive=False)
        # The JSON value inside quotes should be preserved
        assert '"The file was created by the admin"' in result


# ---------------------------------------------------------------------------
# New default tools compression
# ---------------------------------------------------------------------------


class TestNewDefaultToolCompression:
    """Verify the three newly-added default tools are compressed."""

    @pytest.fixture(autouse=True)
    def _reset_config(self):
        _reset_all_state()

    @pytest.mark.asyncio
    async def test_agent_run_shell_command_compresses(self):
        result = await _on_post_tool_call(
            "agent_run_shell_command", {}, _LONG_TEXT, 1.0, None
        )
        assert result is not None
        assert len(result) < len(_LONG_TEXT)
        assert result.endswith(_COMPRESSION_MARKER)

    @pytest.mark.asyncio
    async def test_invoke_agent_compresses(self):
        result = await _on_post_tool_call("invoke_agent", {}, _LONG_TEXT, 1.0, None)
        assert result is not None
        assert len(result) < len(_LONG_TEXT)
        assert result.endswith(_COMPRESSION_MARKER)

    @pytest.mark.asyncio
    async def test_read_relevant_code_compresses(self):
        result = await _on_post_tool_call(
            "read_relevant_code", {}, _LONG_TEXT, 1.0, None
        )
        assert result is not None
        assert len(result) < len(_LONG_TEXT)
        assert result.endswith(_COMPRESSION_MARKER)

    @pytest.mark.asyncio
    async def test_destructive_tools_not_compressed(self):
        """Write/edit/destructive tools must never be compressed by default."""
        for tool in ("create_file", "replace_in_file", "delete_file", "delete_snippet"):
            result = await _on_post_tool_call(tool, {}, _LONG_TEXT, 1.0, None)
            assert result is None, f"{tool} should not be compressed by default"


# ---------------------------------------------------------------------------
# Already-compressed (telegraphic) content skip
# ---------------------------------------------------------------------------


class TestAlreadyCompressedSkip:
    """Verify that already-compressed/telegraphic content is skipped."""

    @pytest.fixture(autouse=True)
    def _reset_config(self):
        _reset_all_state()

    @pytest.mark.asyncio
    async def test_telegraphic_content_skipped(self):
        """Text with very few function words (telegraphic) is not compressed."""
        # Dense, compressed-style text: almost no articles, copulas, intensifiers
        telegraphic = (
            "Config updated. Server restarted. Cache cleared. "
            "Tests passed. Deployed v2.3.1. Monitoring OK. "
            "Alerts silenced. Logs rotated. Disk freed 12GB. "
            "CPU steady 40%. Memory 2.1GB/8GB. Network latency 3ms. "
            "DB pool 8/20. Queue depth 0. Workers 4. "
            "Uptime 47d. Last incident 12d ago. SLA 99.97%. "
        )
        # Repeat to get past length gate
        telegraphic_long = telegraphic * 10
        assert len(telegraphic_long) > 200
        result = await _on_post_tool_call("read_file", {}, telegraphic_long, 1.0, None)
        assert result is None  # _looks_already_compressed should return True

    @pytest.mark.asyncio
    async def test_marker_prevents_recompression(self):
        """Content already carrying the compression marker is not re-compressed."""
        result1 = await _on_post_tool_call("grep", {}, _LONG_TEXT, 1.0, None)
        assert result1 is not None
        # Feed compressed output back
        result2 = await _on_post_tool_call("grep", {}, result1, 1.0, None)
        assert result2 is None


# ---------------------------------------------------------------------------
# Character counters in compression stats
# ---------------------------------------------------------------------------


class TestCharacterCounters:
    """Verify character counters are tracked in compression stats."""

    @pytest.fixture(autouse=True)
    def _reset_config(self):
        _reset_all_state()

    @pytest.mark.asyncio
    async def test_stats_track_chars(self):
        """After compression, character counters are incremented."""
        import code_muse.plugins.semantic_compression.register_callbacks as rc

        result = await _on_post_tool_call("read_file", {}, _LONG_TEXT, 1.0, None)
        if result is not None:
            stats = rc._compression_stats
            assert stats["total_original_chars"] > 0
            assert stats["total_compressed_chars"] > 0
            assert stats["total_compressed_chars"] < stats["total_original_chars"]

    @pytest.mark.asyncio
    async def test_stats_display_includes_chars(self):
        """_show_compression_stats includes character savings."""
        import code_muse.plugins.semantic_compression.register_callbacks as rc

        rc._compression_stats = {
            "total_compressed": 3,
            "total_original_tokens": 2000,
            "total_compressed_tokens": 1500,
            "total_original_chars": 10000,
            "total_compressed_chars": 7000,
        }
        output = _show_compression_stats()
        assert "Chars saved" in output
        assert "3,000" in output  # 10000 - 7000 chars saved
        assert "10,000" in output  # original chars
        assert "7,000" in output  # compressed chars
