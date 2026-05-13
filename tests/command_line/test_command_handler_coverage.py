"""Tests for command_handler.py - 100% coverage."""

from unittest.mock import MagicMock, patch


class TestEnsurePluginsLoaded:
    """Test that _ensure_plugins_loaded delegates to plugins.load_plugin_callbacks.

    The local _PLUGINS_LOADED flag has been removed; all idempotency lives
    inside plugins.load_plugin_callbacks().
    """

    @patch("code_muse.plugins.load_plugin_callbacks")
    def test_calls_load_plugin_callbacks(self, mock_load):
        from code_muse.command_line.command_handler import _ensure_plugins_loaded

        _ensure_plugins_loaded()
        mock_load.assert_called_once()

    @patch("code_muse.plugins.load_plugin_callbacks")
    def test_delegates_idempotency(self, mock_load):
        """Calling twice invokes load_plugin_callbacks each time;
        idempotency is handled inside load_plugin_callbacks itself.
        """
        from code_muse.command_line.command_handler import _ensure_plugins_loaded

        _ensure_plugins_loaded()
        _ensure_plugins_loaded()
        assert mock_load.call_count == 2

    @patch("code_muse.plugins.load_plugin_callbacks", side_effect=Exception("boom"))
    @patch("code_muse.messaging.emit_warning")
    def test_plugin_load_error(self, mock_warn, mock_load):
        from code_muse.command_line.command_handler import _ensure_plugins_loaded

        _ensure_plugins_loaded()  # Should not raise
        mock_warn.assert_called_once()

    @patch("code_muse.plugins.load_plugin_callbacks", side_effect=Exception("boom"))
    @patch("code_muse.messaging.emit_warning", side_effect=Exception("double boom"))
    def test_plugin_load_error_warning_fails(self, mock_warn, mock_load):
        from code_muse.command_line.command_handler import _ensure_plugins_loaded

        _ensure_plugins_loaded()  # Should not raise even if warning fails


class TestGetCommandsHelp:
    @patch("code_muse.command_line.command_handler._ensure_plugins_loaded")
    @patch("code_muse.command_line.command_registry.get_unique_commands")
    @patch("code_muse.callbacks.on_custom_command_help", return_value=[])
    def test_basic_help(self, mock_custom, mock_cmds, mock_plugins):
        from code_muse.command_line.command_handler import get_commands_help
        from code_muse.command_line.command_registry import CommandInfo

        mock_cmds.return_value = [
            CommandInfo(name="test", description="Test command", handler=lambda x: True)
        ]
        result = get_commands_help()
        assert result is not None

    @patch("code_muse.command_line.command_handler._ensure_plugins_loaded")
    @patch(
        "code_muse.command_line.command_registry.get_unique_commands", return_value=[]
    )
    @patch("code_muse.callbacks.on_custom_command_help")
    def test_custom_command_tuple(self, mock_custom, mock_cmds, mock_plugins):
        from code_muse.command_line.command_handler import get_commands_help

        mock_custom.return_value = [("mycmd", "My description")]
        result = get_commands_help()
        assert result is not None

    @patch("code_muse.command_line.command_handler._ensure_plugins_loaded")
    @patch(
        "code_muse.command_line.command_registry.get_unique_commands", return_value=[]
    )
    @patch("code_muse.callbacks.on_custom_command_help")
    def test_custom_command_list_of_tuples(self, mock_custom, mock_cmds, mock_plugins):
        from code_muse.command_line.command_handler import get_commands_help

        mock_custom.return_value = [[("cmd1", "desc1"), ("cmd2", "desc2")]]
        result = get_commands_help()
        assert result is not None

    @patch("code_muse.command_line.command_handler._ensure_plugins_loaded")
    @patch(
        "code_muse.command_line.command_registry.get_unique_commands", return_value=[]
    )
    @patch("code_muse.callbacks.on_custom_command_help")
    def test_custom_command_list_of_strings(self, mock_custom, mock_cmds, mock_plugins):
        from code_muse.command_line.command_handler import get_commands_help

        mock_custom.return_value = [["/mycmd - My description"]]
        result = get_commands_help()
        assert result is not None

    @patch("code_muse.command_line.command_handler._ensure_plugins_loaded")
    @patch(
        "code_muse.command_line.command_registry.get_unique_commands", return_value=[]
    )
    @patch("code_muse.callbacks.on_custom_command_help")
    def test_custom_command_none_entries(self, mock_custom, mock_cmds, mock_plugins):
        from code_muse.command_line.command_handler import get_commands_help

        mock_custom.return_value = [None, None]
        result = get_commands_help()
        assert result is not None

    @patch("code_muse.command_line.command_handler._ensure_plugins_loaded")
    @patch(
        "code_muse.command_line.command_registry.get_unique_commands", return_value=[]
    )
    @patch("code_muse.callbacks.on_custom_command_help", side_effect=Exception("err"))
    def test_custom_command_exception(self, mock_custom, mock_cmds, mock_plugins):
        from code_muse.command_line.command_handler import get_commands_help

        result = get_commands_help()  # Should not raise
        assert result is not None

    @patch("code_muse.command_line.command_handler._ensure_plugins_loaded")
    @patch(
        "code_muse.command_line.command_registry.get_unique_commands", return_value=[]
    )
    @patch("code_muse.callbacks.on_custom_command_help", return_value=[])
    def test_empty_commands(self, mock_custom, mock_cmds, mock_plugins):
        from code_muse.command_line.command_handler import get_commands_help

        result = get_commands_help()
        assert result is not None

    @patch("code_muse.command_line.command_handler._ensure_plugins_loaded")
    @patch("code_muse.command_line.command_registry.get_unique_commands")
    @patch("code_muse.callbacks.on_custom_command_help", return_value=[])
    def test_long_description_truncated(self, mock_custom, mock_cmds, mock_plugins):
        """Cover line 83 - truncate_desc with long description."""
        from code_muse.command_line.command_handler import get_commands_help
        from code_muse.command_line.command_registry import CommandInfo

        mock_cmds.return_value = [
            CommandInfo(name="longdesc", description="x" * 200, handler=lambda x: True)
        ]
        result = get_commands_help()
        assert result is not None


class TestHandleCommand:
    @patch("code_muse.command_line.command_handler._ensure_plugins_loaded")
    @patch("code_muse.command_line.command_registry.get_command")
    def test_registered_command(self, mock_get, mock_plugins):
        from code_muse.command_line.command_handler import handle_command

        mock_handler = MagicMock(return_value=True)
        mock_get.return_value = MagicMock(handler=mock_handler)
        result = handle_command("/test")
        assert result is True

    @patch("code_muse.command_line.command_handler._ensure_plugins_loaded")
    @patch("code_muse.command_line.command_registry.get_command", return_value=None)
    @patch("code_muse.callbacks.on_custom_command", return_value=[True])
    def test_custom_command_returns_true(self, mock_custom, mock_get, mock_plugins):
        from code_muse.command_line.command_handler import handle_command

        result = handle_command("/mycustom")
        assert result is True

    @patch("code_muse.command_line.command_handler._ensure_plugins_loaded")
    @patch("code_muse.command_line.command_registry.get_command", return_value=None)
    @patch("code_muse.callbacks.on_custom_command", return_value=["some text"])
    @patch("code_muse.messaging.emit_info")
    def test_custom_command_returns_string(
        self, mock_emit, mock_custom, mock_get, mock_plugins
    ):
        from code_muse.command_line.command_handler import handle_command

        result = handle_command("/mycustom")
        assert result is True

    @patch("code_muse.command_line.command_handler._ensure_plugins_loaded")
    @patch("code_muse.command_line.command_registry.get_command", return_value=None)
    @patch("code_muse.callbacks.on_custom_command", return_value=["some text"])
    @patch("code_muse.messaging.emit_info", side_effect=Exception("oops"))
    def test_custom_command_string_emit_fails(
        self, mock_emit, mock_custom, mock_get, mock_plugins
    ):
        from code_muse.command_line.command_handler import handle_command

        result = handle_command("/mycustom")
        assert result is True

    @patch("code_muse.command_line.command_handler._ensure_plugins_loaded")
    @patch("code_muse.command_line.command_registry.get_command", return_value=None)
    @patch("code_muse.callbacks.on_custom_command", return_value=[None])
    @patch("code_muse.messaging.emit_warning")
    def test_unknown_command(self, mock_warn, mock_custom, mock_get, mock_plugins):
        from code_muse.command_line.command_handler import handle_command

        result = handle_command("/unknowncmd")
        assert result is True
        mock_warn.assert_called_once()

    @patch("code_muse.command_line.command_handler._ensure_plugins_loaded")
    @patch("code_muse.command_line.command_registry.get_command", return_value=None)
    @patch("code_muse.callbacks.on_custom_command", return_value=[None])
    @patch("code_muse.messaging.emit_info")
    @patch(
        "code_muse.command_line.model_picker_completion.get_active_model",
        return_value="gpt-4",
    )
    def test_bare_slash_shows_model(
        self, mock_model, mock_info, mock_custom, mock_get, mock_plugins
    ):
        from code_muse.command_line.command_handler import handle_command

        result = handle_command("/")
        assert result is True

    def test_non_command(self):
        from code_muse.command_line.command_handler import handle_command

        result = handle_command("not a command")
        assert result is False

    @patch("code_muse.command_line.command_handler._ensure_plugins_loaded")
    @patch("code_muse.command_line.command_registry.get_command", return_value=None)
    @patch("code_muse.callbacks.on_custom_command", side_effect=Exception("plugin err"))
    @patch("code_muse.messaging.emit_warning")
    def test_custom_command_hook_error(
        self, mock_warn, mock_custom, mock_get, mock_plugins
    ):
        from code_muse.command_line.command_handler import handle_command

        result = handle_command("/failing")
        assert result is True

    @patch("code_muse.command_line.command_handler._ensure_plugins_loaded")
    @patch("code_muse.command_line.command_registry.get_command", return_value=None)
    @patch("code_muse.callbacks.on_custom_command")
    def test_markdown_command_result(self, mock_custom, mock_get, mock_plugins):
        from code_muse.command_line.command_handler import handle_command
        from code_muse.command_line.types import MarkdownCommandResult

        mock_result = MarkdownCommandResult("# Markdown content")
        mock_custom.return_value = [mock_result]
        result = handle_command("/mycmd")
        assert result == "# Markdown content"
