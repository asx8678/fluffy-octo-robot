import configparser
import os
from pathlib import Path
from unittest.mock import MagicMock, mock_open, patch

import pytest

from code_muse import config as cp_config
from code_muse.config import parser as _parser
from code_muse.config import paths as _paths

# Define constants used in config.py to avoid direct import if they change
CONFIG_DIR_NAME = ".muse"
CONFIG_FILE_NAME = "muse.cfg"
DEFAULT_SECTION_NAME = "muse"


@pytest.fixture
def mock_config_paths(monkeypatch):
    # Ensure that tests don't interact with the actual user's config
    mock_home = "/mock_home"
    mock_config_dir = Path(mock_home) / CONFIG_DIR_NAME
    mock_config_file = Path(mock_config_dir) / CONFIG_FILE_NAME
    # XDG directories for the new directory structure
    mock_data_dir = Path(mock_home) / ".local" / "share" / "code_muse"
    mock_cache_dir = Path(mock_home) / ".cache" / "code_muse"
    mock_state_dir = Path(mock_home) / ".local" / "state" / "code_muse"
    mock_skills_dir = Path(mock_data_dir) / "skills"

    monkeypatch.setattr(_paths, "CONFIG_DIR", mock_config_dir)
    monkeypatch.setattr(_paths, "CONFIG_FILE", mock_config_file)
    monkeypatch.setattr(_paths, "DATA_DIR", mock_data_dir)
    monkeypatch.setattr(_paths, "CACHE_DIR", mock_cache_dir)
    monkeypatch.setattr(_paths, "STATE_DIR", mock_state_dir)
    monkeypatch.setattr(_paths, "SKILLS_DIR", mock_skills_dir)
    monkeypatch.setattr(
        os.path,
        "expanduser",
        lambda path: mock_home if path == "~" else os.path.expanduser(path),
    )
    # Reset the global config cache so tests don't pollute each other
    monkeypatch.setattr(_parser, "_config_cache", None)
    return mock_config_dir, mock_config_file


class TestEnsureConfigExists:
    def test_no_config_dir_or_file_prompts_and_creates(self, tmp_path, monkeypatch):
        cfg_dir = tmp_path / "config"
        cfg_file = cfg_dir / CONFIG_FILE_NAME
        monkeypatch.setattr(_paths, "CONFIG_DIR", cfg_dir)
        monkeypatch.setattr(_paths, "CONFIG_FILE", cfg_file)
        monkeypatch.setattr(_paths, "DATA_DIR", tmp_path / "data")
        monkeypatch.setattr(_paths, "CACHE_DIR", tmp_path / "cache")
        monkeypatch.setattr(_paths, "STATE_DIR", tmp_path / "state")
        monkeypatch.setattr(_paths, "SKILLS_DIR", tmp_path / "skills")

        monkeypatch.setattr(
            "builtins.input",
            MagicMock(side_effect=["TestPuppy", "TestOwner"]),
        )

        config_parser = cp_config.ensure_config_exists()

        assert cfg_dir.exists()
        assert cfg_file.exists()
        assert config_parser.sections() == [DEFAULT_SECTION_NAME]
        assert config_parser.get(DEFAULT_SECTION_NAME, "agent_name") == "TestPuppy"
        assert config_parser.get(DEFAULT_SECTION_NAME, "owner_name") == "TestOwner"

    def test_config_dir_exists_file_does_not_prompts_and_creates(
        self, tmp_path, monkeypatch
    ):
        cfg_dir = tmp_path / "config"
        cfg_file = cfg_dir / "muse.cfg"
        cfg_dir.mkdir()
        monkeypatch.setattr(_paths, "CONFIG_DIR", cfg_dir)
        monkeypatch.setattr(_paths, "CONFIG_FILE", cfg_file)
        monkeypatch.setattr(_paths, "DATA_DIR", tmp_path / "data")
        monkeypatch.setattr(_paths, "CACHE_DIR", tmp_path / "cache")
        monkeypatch.setattr(_paths, "STATE_DIR", tmp_path / "state")
        monkeypatch.setattr(_paths, "SKILLS_DIR", tmp_path / "skills")

        monkeypatch.setattr(
            "builtins.input",
            MagicMock(side_effect=["DirExistsPuppy", "DirExistsOwner"]),
        )

        config_parser = cp_config.ensure_config_exists()

        assert cfg_file.exists()
        assert config_parser.get(DEFAULT_SECTION_NAME, "agent_name") == "DirExistsPuppy"
        assert config_parser.get(DEFAULT_SECTION_NAME, "owner_name") == "DirExistsOwner"

    def test_config_file_exists_and_complete_no_prompt_no_write(
        self, tmp_path, monkeypatch
    ):
        cfg_dir = tmp_path / "config"
        cfg_file = cfg_dir / "muse.cfg"
        cfg_dir.mkdir()
        cp = configparser.ConfigParser()
        cp[DEFAULT_SECTION_NAME] = {
            "agent_name": "ExistingPuppy",
            "owner_name": "ExistingOwner",
        }
        with open(cfg_file, "w", encoding="utf-8") as f:
            cp.write(f)

        monkeypatch.setattr(_paths, "CONFIG_DIR", cfg_dir)
        monkeypatch.setattr(_paths, "CONFIG_FILE", cfg_file)
        monkeypatch.setattr(_paths, "DATA_DIR", tmp_path / "data")
        monkeypatch.setattr(_paths, "CACHE_DIR", tmp_path / "cache")
        monkeypatch.setattr(_paths, "STATE_DIR", tmp_path / "state")
        monkeypatch.setattr(_paths, "SKILLS_DIR", tmp_path / "skills")

        mock_input = MagicMock()
        monkeypatch.setattr("builtins.input", mock_input)

        returned_config_parser = cp_config.ensure_config_exists()

        mock_input.assert_not_called()
        assert (
            returned_config_parser.get(DEFAULT_SECTION_NAME, "agent_name")
            == "ExistingPuppy"
        )

    def test_config_file_exists_missing_one_key_prompts_and_writes(
        self, tmp_path, monkeypatch
    ):
        cfg_dir = tmp_path / "config"
        cfg_file = cfg_dir / "muse.cfg"
        cfg_dir.mkdir()
        cp = configparser.ConfigParser()
        cp[DEFAULT_SECTION_NAME] = {"agent_name": "PartialPuppy"}
        with open(cfg_file, "w", encoding="utf-8") as f:
            cp.write(f)

        monkeypatch.setattr(_paths, "CONFIG_DIR", cfg_dir)
        monkeypatch.setattr(_paths, "CONFIG_FILE", cfg_file)
        monkeypatch.setattr(_paths, "DATA_DIR", tmp_path / "data")
        monkeypatch.setattr(_paths, "CACHE_DIR", tmp_path / "cache")
        monkeypatch.setattr(_paths, "STATE_DIR", tmp_path / "state")
        monkeypatch.setattr(_paths, "SKILLS_DIR", tmp_path / "skills")

        monkeypatch.setattr(
            "builtins.input",
            MagicMock(side_effect=["PartialOwnerFilled"]),
        )

        returned_config_parser = cp_config.ensure_config_exists()

        assert (
            returned_config_parser.get(DEFAULT_SECTION_NAME, "agent_name")
            == "PartialPuppy"
        )
        assert (
            returned_config_parser.get(DEFAULT_SECTION_NAME, "owner_name")
            == "PartialOwnerFilled"
        )


class TestGetValue:
    @patch("configparser.ConfigParser")
    def test_get_value_exists(self, mock_config_parser_class, mock_config_paths):
        _, mock_cfg_file = mock_config_paths
        mock_parser_instance = MagicMock()
        mock_parser_instance.get.return_value = "test_value"
        mock_config_parser_class.return_value = mock_parser_instance

        val = cp_config.get_value("test_key")

        mock_config_parser_class.assert_called_once()
        mock_parser_instance.read.assert_called_once_with(mock_cfg_file)
        mock_parser_instance.get.assert_called_once_with(
            DEFAULT_SECTION_NAME, "test_key", fallback=None
        )
        assert val == "test_value"

    @patch("configparser.ConfigParser")
    def test_get_value_not_exists(self, mock_config_parser_class, mock_config_paths):
        _, mock_cfg_file = mock_config_paths
        mock_parser_instance = MagicMock()
        mock_parser_instance.get.return_value = None  # Simulate key not found
        mock_config_parser_class.return_value = mock_parser_instance

        val = cp_config.get_value("missing_key")

        assert val is None

    @patch("configparser.ConfigParser")
    def test_get_value_config_file_not_exists_graceful(
        self, mock_config_parser_class, mock_config_paths
    ):
        _, mock_cfg_file = mock_config_paths
        mock_parser_instance = MagicMock()
        mock_parser_instance.get.return_value = None
        mock_config_parser_class.return_value = mock_parser_instance

        val = cp_config.get_value("any_key")
        assert val is None


class TestSimpleGetters:
    @patch("code_muse.config.parser.get_value")
    def test_get_agent_name_exists(self, mock_get_value):
        mock_get_value.return_value = "MyPuppy"
        assert cp_config.get_agent_name() == "MyPuppy"
        mock_get_value.assert_called_once_with("agent_name")

    @patch("code_muse.config.parser.get_value")
    def test_get_agent_name_not_exists_uses_default(self, mock_get_value):
        mock_get_value.return_value = None
        assert cp_config.get_agent_name() == "Muse"  # Default value
        mock_get_value.assert_called_once_with("agent_name")

    @patch("code_muse.config.parser.get_value")
    def test_get_owner_name_exists(self, mock_get_value):
        mock_get_value.return_value = "MyOwner"
        assert cp_config.get_owner_name() == "MyOwner"
        mock_get_value.assert_called_once_with("owner_name")

    @patch("code_muse.config.parser.get_value")
    def test_get_owner_name_not_exists_uses_default(self, mock_get_value):
        mock_get_value.return_value = None
        assert cp_config.get_owner_name() == "Creator"  # Default value
        mock_get_value.assert_called_once_with("owner_name")


class TestGetConfigKeys:
    @patch("configparser.ConfigParser")
    def test_get_config_keys_with_existing_keys(
        self, mock_config_parser_class, mock_config_paths
    ):
        _, mock_cfg_file = mock_config_paths
        mock_parser_instance = MagicMock()

        section_proxy = {"key1": "val1", "key2": "val2"}
        mock_parser_instance.__contains__.return_value = True
        mock_parser_instance.__getitem__.return_value = section_proxy
        mock_config_parser_class.return_value = mock_parser_instance

        keys = cp_config.get_config_keys()

        mock_parser_instance.read.assert_called_once_with(mock_cfg_file)
        assert keys == sorted(
            [
                "allow_recursion",
                "auto_approve",
                "auto_save_session",
                "banner_color_agent_reasoning",
                "banner_color_agent_response",
                "banner_color_create_file",
                "banner_color_delete_snippet",
                "banner_color_directory_listing",
                "banner_color_edit_file",
                "banner_color_grep",
                "banner_color_invoke_agent",
                "banner_color_list_agents",
                "banner_color_read_file",
                "banner_color_replace_in_file",
                "banner_color_shell_command",
                "banner_color_shell_passthrough",
                "banner_color_subagent_response",
                "banner_color_terminal_tool",
                "banner_color_thinking",
                "banner_color_universal_constructor",
                "cancel_agent_key",
                "compaction_strategy",
                "compaction_threshold",
                "default_agent",
                "diff_context_lines",
                "enable_pack_agents",
                "enable_streaming",
                "enable_universal_constructor",
                "http2",
                "key1",
                "key2",
                "max_consecutive_tool_errors",
                "max_critic_retries",
                "max_hook_retries",
                "max_saved_sessions",
                "max_tool_calls",
                "message_limit",
                "model",
                "openai_reasoning_effort",
                "openai_reasoning_summary",
                "openai_verbosity",
                "overall_run_timeout",
                "protected_token_count",
                "resume_message_count",
                "summarization_model",
                "temperature",
                "total_tokens_limit",
                "yolo_mode",
            ]
        )

    @patch("configparser.ConfigParser")
    def test_get_config_keys_empty_config(
        self, mock_config_parser_class, mock_config_paths
    ):
        _, mock_cfg_file = mock_config_paths
        mock_parser_instance = MagicMock()
        mock_parser_instance.__contains__.return_value = False
        mock_config_parser_class.return_value = mock_parser_instance

        keys = cp_config.get_config_keys()
        assert keys == sorted(
            [
                "allow_recursion",
                "auto_approve",
                "auto_save_session",
                "banner_color_agent_reasoning",
                "banner_color_agent_response",
                "banner_color_create_file",
                "banner_color_delete_snippet",
                "banner_color_directory_listing",
                "banner_color_edit_file",
                "banner_color_grep",
                "banner_color_invoke_agent",
                "banner_color_list_agents",
                "banner_color_read_file",
                "banner_color_replace_in_file",
                "banner_color_shell_command",
                "banner_color_shell_passthrough",
                "banner_color_subagent_response",
                "banner_color_terminal_tool",
                "banner_color_thinking",
                "banner_color_universal_constructor",
                "cancel_agent_key",
                "compaction_strategy",
                "compaction_threshold",
                "default_agent",
                "diff_context_lines",
                "enable_pack_agents",
                "enable_streaming",
                "enable_universal_constructor",
                "http2",
                "max_consecutive_tool_errors",
                "max_critic_retries",
                "max_hook_retries",
                "max_saved_sessions",
                "max_tool_calls",
                "message_limit",
                "model",
                "openai_reasoning_effort",
                "openai_reasoning_summary",
                "openai_verbosity",
                "overall_run_timeout",
                "protected_token_count",
                "resume_message_count",
                "summarization_model",
                "temperature",
                "total_tokens_limit",
                "yolo_mode",
            ]
        )


class TestSetConfigValue:
    @patch("configparser.ConfigParser")
    @patch("builtins.open", new_callable=mock_open)
    def test_set_config_value_new_key_section_exists(
        self, mock_file_open, mock_config_parser_class, mock_config_paths
    ):
        _, mock_cfg_file = mock_config_paths
        mock_parser_instance = MagicMock()

        section_dict = {}
        mock_parser_instance.read.return_value = [mock_cfg_file]
        mock_parser_instance.__contains__.return_value = True
        mock_parser_instance.__getitem__.return_value = section_dict
        mock_config_parser_class.return_value = mock_parser_instance

        cp_config.set_config_value("a_new_key", "a_new_value")

        assert section_dict["a_new_key"] == "a_new_value"
        mock_file_open.assert_called_once_with(mock_cfg_file, "w", encoding="utf-8")
        mock_parser_instance.write.assert_called_once_with(mock_file_open())

    @patch("configparser.ConfigParser")
    @patch("builtins.open", new_callable=mock_open)
    def test_set_config_value_update_existing_key(
        self, mock_file_open, mock_config_parser_class, mock_config_paths
    ):
        _, mock_cfg_file = mock_config_paths
        mock_parser_instance = MagicMock()

        section_dict = {"existing_key": "old_value"}
        mock_parser_instance.read.return_value = [mock_cfg_file]
        mock_parser_instance.__contains__.return_value = True
        mock_parser_instance.__getitem__.return_value = section_dict
        mock_config_parser_class.return_value = mock_parser_instance

        cp_config.set_config_value("existing_key", "updated_value")

        assert section_dict["existing_key"] == "updated_value"
        mock_file_open.assert_called_once_with(mock_cfg_file, "w", encoding="utf-8")
        mock_parser_instance.write.assert_called_once_with(mock_file_open())

    @patch("configparser.ConfigParser")
    @patch("builtins.open", new_callable=mock_open)
    def test_set_config_value_section_does_not_exist_creates_it(
        self, mock_file_open, mock_config_parser_class, mock_config_paths
    ):
        _, mock_cfg_file = mock_config_paths
        mock_parser_instance = MagicMock()

        created_sections_store = {}

        def mock_contains_check(section_name):
            return section_name in created_sections_store

        def mock_setitem_for_section_creation(section_name, value_usually_empty_dict):
            created_sections_store[section_name] = value_usually_empty_dict

        def mock_getitem_for_section_access(section_name):
            return created_sections_store[section_name]

        mock_parser_instance.read.return_value = [mock_cfg_file]
        mock_parser_instance.__contains__.side_effect = mock_contains_check
        mock_parser_instance.__setitem__.side_effect = mock_setitem_for_section_creation
        mock_parser_instance.__getitem__.side_effect = mock_getitem_for_section_access

        mock_config_parser_class.return_value = mock_parser_instance

        cp_config.set_config_value("key_in_new_section", "value_in_new_section")

        assert DEFAULT_SECTION_NAME in created_sections_store
        assert (
            created_sections_store[DEFAULT_SECTION_NAME]["key_in_new_section"]
            == "value_in_new_section"
        )

        mock_file_open.assert_called_once_with(mock_cfg_file, "w", encoding="utf-8")
        mock_parser_instance.write.assert_called_once_with(mock_file_open())


class TestModelName:
    def setup_method(self):
        # Reset session model before each test to avoid cross-test pollution
        cp_config.reset_session_model()
        cp_config.clear_model_cache()

    @patch("code_muse.config.parser.get_value")
    @patch("code_muse.config.models._validate_model_exists")
    def test_get_model_name_exists(self, mock_validate_model_exists, mock_get_value):
        mock_get_value.return_value = "test_model_from_config"
        mock_validate_model_exists.return_value = True
        assert cp_config.get_global_model_name() == "test_model_from_config"
        mock_get_value.assert_called_once_with("model")
        mock_validate_model_exists.assert_called_once_with("test_model_from_config")

    @patch("configparser.ConfigParser")
    @patch("builtins.open", new_callable=mock_open)
    def test_set_model_name(
        self, mock_file_open, mock_config_parser_class, mock_config_paths
    ):
        _, mock_cfg_file = mock_config_paths
        mock_parser_instance = MagicMock()

        section_dict = {}
        # This setup ensures that config[DEFAULT_SECTION_NAME] operations
        # work on section_dict and that the section is considered to exist
        # or is created as needed.
        mock_parser_instance.read.return_value = [mock_cfg_file]

        # Simulate that the section exists or will be created and then available
        def get_section_or_create(name):
            if name == DEFAULT_SECTION_NAME:
                # Ensure subsequent checks for section existence pass
                mock_parser_instance.__contains__ = lambda s_name: (
                    s_name == DEFAULT_SECTION_NAME
                )
                return section_dict
            raise KeyError(name)

        mock_parser_instance.__getitem__.side_effect = get_section_or_create
        # Initial check for section existence (might be False if section needs creation)
        # We'll simplify by assuming it's True after first access or creation attempt.
        _section_exists_initially = False

        def initial_contains_check(s_name):
            nonlocal _section_exists_initially
            if s_name == DEFAULT_SECTION_NAME:
                if _section_exists_initially:
                    return True
                _section_exists_initially = (
                    True  # Simulate it's created on first miss then setitem
                )
                return False
            return False

        mock_parser_instance.__contains__.side_effect = initial_contains_check

        def mock_setitem_for_section(name, value):
            if name == DEFAULT_SECTION_NAME:  # For config[DEFAULT_SECTION_NAME] = {}
                pass  # section_dict is already our target via __getitem__ side_effect
            else:  # For config[DEFAULT_SECTION_NAME][key] = value
                section_dict[name] = value

        mock_parser_instance.__setitem__.side_effect = mock_setitem_for_section
        mock_config_parser_class.return_value = mock_parser_instance

        cp_config.set_model_name("super_model_7000")

        assert section_dict["model"] == "super_model_7000"
        mock_file_open.assert_called_once_with(mock_cfg_file, "w", encoding="utf-8")
        mock_parser_instance.write.assert_called_once_with(mock_file_open())


class TestGetYoloMode:
    @patch("code_muse.config.parser.get_value")
    def test_get_yolo_mode_from_config_true(self, mock_get_value):
        true_values = ["true", "1", "YES", "ON"]
        for val in true_values:
            mock_get_value.reset_mock()
            mock_get_value.return_value = val
            assert cp_config.get_yolo_mode() is True, f"Failed for config value: {val}"
            mock_get_value.assert_called_once_with("yolo_mode")

    @patch("code_muse.config.parser.get_value")
    def test_get_yolo_mode_not_in_config_defaults_false(self, mock_get_value):
        """Yolo mode defaults to False (safe) when not explicitly set."""
        mock_get_value.return_value = None

        assert cp_config.get_yolo_mode() is False
        mock_get_value.assert_called_once_with("yolo_mode")


class TestCommandHistory:
    def test_initialize_command_history_file_creates_new_file(
        self, tmp_path, monkeypatch
    ):
        hist_file = tmp_path / "state" / "history.txt"
        monkeypatch.setattr(_paths, "STATE_DIR", tmp_path / "state")
        monkeypatch.setattr(_paths, "COMMAND_HISTORY_FILE", hist_file)
        monkeypatch.setattr(os.path, "expanduser", lambda _: str(tmp_path))

        cp_config.initialize_command_history_file()

        assert hist_file.exists()

    def test_initialize_command_history_file_migrates_old_file(
        self, tmp_path, monkeypatch
    ):
        state_dir = tmp_path / "state"
        hist_file = state_dir / "history.txt"
        old_file = tmp_path / ".muse_history.txt"
        old_file.write_text("old history")

        monkeypatch.setattr(_paths, "STATE_DIR", state_dir)
        monkeypatch.setattr(_paths, "COMMAND_HISTORY_FILE", hist_file)
        monkeypatch.setattr(os.path, "expanduser", lambda _: str(tmp_path))

        cp_config.initialize_command_history_file()

        assert hist_file.exists()
        assert hist_file.read_text() == "old history"

    def test_initialize_command_history_file_file_exists(self, tmp_path, monkeypatch):
        hist_file = tmp_path / "state" / "history.txt"
        hist_file.parent.mkdir(parents=True)
        hist_file.write_text("existing")

        monkeypatch.setattr(_paths, "STATE_DIR", tmp_path / "state")
        monkeypatch.setattr(_paths, "COMMAND_HISTORY_FILE", hist_file)

        cp_config.initialize_command_history_file()

        # Should not modify existing file
        assert hist_file.read_text() == "existing"

    def test_save_command_to_history_with_timestamp(self, tmp_path, monkeypatch):
        hist_file = tmp_path / "history.txt"
        monkeypatch.setattr(_paths, "COMMAND_HISTORY_FILE", hist_file)

        cp_config.save_command_to_history("test command")

        content = hist_file.read_text()
        assert content.startswith("\n# ")
        assert content.endswith("\ntest command\n")

    def test_save_command_to_history_handles_error(self, tmp_path, monkeypatch):
        hist_file = tmp_path / "nonexistent" / "history.txt"
        monkeypatch.setattr(_paths, "COMMAND_HISTORY_FILE", hist_file)

        # Should not raise
        cp_config.save_command_to_history("test command")
        cp_config.reset_session_model()

    @patch("code_muse.config.parser.get_value")
    @patch("code_muse.config.models._validate_model_exists")
    @patch("code_muse.config.models._default_model_from_models_json")
    def test_get_model_name_no_stored_model(
        self, mock_default_model, mock_validate_model_exists, mock_get_value
    ):
        # When no model is stored in config, get_model_name should return
        # the default model
        mock_get_value.return_value = None
        mock_default_model.return_value = "synthetic-GLM-5.1"

        result = cp_config.get_global_model_name()

        assert result == "synthetic-GLM-5.1"
        mock_get_value.assert_called_once_with("model")
        mock_validate_model_exists.assert_not_called()
        mock_default_model.assert_called_once()

    @patch("code_muse.config.parser.get_value")
    @patch("code_muse.config.models._validate_model_exists")
    @patch("code_muse.config.models._default_model_from_models_json")
    def test_get_model_name_invalid_model(
        self, mock_default_model, mock_validate_model_exists, mock_get_value
    ):
        # When stored model doesn't exist in models.json, should return default model
        mock_get_value.return_value = "invalid-model"
        mock_validate_model_exists.return_value = False
        mock_default_model.return_value = "synthetic-GLM-5.1"

        result = cp_config.get_global_model_name()

        assert result == "synthetic-GLM-5.1"
        mock_get_value.assert_called_once_with("model")
        mock_validate_model_exists.assert_called_once_with("invalid-model")
        mock_default_model.assert_called_once()

    # NOTE: Tests that mock ModelFactory.load_config have been removed
    # because they can't work due to a circular import issue in the
    # codebase. The circular import:
    # model_factory -> messaging -> rich_renderer -> tools -> agent_tools
    # -> model_factory. This causes _default_model_from_models_json() to
    # always fall back to 'gpt-5' when trying to import ModelFactory.


class TestTemperatureConfig:
    """Tests for the temperature configuration functions."""

    @patch("code_muse.config.parser.get_value")
    def test_get_temperature_returns_none_when_not_set(self, mock_get_value):
        """Temperature should return None when not configured."""
        mock_get_value.return_value = None
        result = cp_config.get_temperature()
        assert result is None
        mock_get_value.assert_called_once_with("temperature")

    @patch("code_muse.config.parser.get_value")
    def test_get_temperature_returns_none_for_empty_string(self, mock_get_value):
        """Temperature should return None for empty string."""
        mock_get_value.return_value = ""
        result = cp_config.get_temperature()
        assert result is None

    @patch("code_muse.config.parser.get_value")
    def test_get_temperature_returns_float_value(self, mock_get_value):
        """Temperature should return a float when set."""
        mock_get_value.return_value = "0.7"
        result = cp_config.get_temperature()
        assert result == 0.7
        assert isinstance(result, float)

    @patch("code_muse.config.parser.get_value")
    def test_get_temperature_clamps_to_max(self, mock_get_value):
        """Temperature should be clamped to max 2.0."""
        mock_get_value.return_value = "5.0"
        result = cp_config.get_temperature()
        assert result == 2.0

    @patch("code_muse.config.parser.get_value")
    def test_get_temperature_clamps_to_min(self, mock_get_value):
        """Temperature should be clamped to min 0.0."""
        mock_get_value.return_value = "-1.0"
        result = cp_config.get_temperature()
        assert result == 0.0

    @patch("code_muse.config.parser.get_value")
    def test_get_temperature_handles_invalid_value(self, mock_get_value):
        """Temperature should return None for invalid values."""
        mock_get_value.return_value = "not_a_number"
        result = cp_config.get_temperature()
        assert result is None

    @patch("code_muse.config.parser.set_config_value")
    def test_set_temperature_with_value(self, mock_set_config_value):
        """Setting temperature should store it as a string."""
        cp_config.set_temperature(0.7)
        mock_set_config_value.assert_called_once_with("temperature", "0.7")

    @patch("code_muse.config.parser.set_config_value")
    def test_set_temperature_clamps_value(self, mock_set_config_value):
        """Setting temperature should clamp out-of-range values."""
        cp_config.set_temperature(5.0)
        mock_set_config_value.assert_called_once_with("temperature", "2.0")

    @patch("code_muse.config.parser.set_config_value")
    def test_set_temperature_to_none_clears_value(self, mock_set_config_value):
        """Setting temperature to None should clear it."""
        cp_config.set_temperature(None)
        mock_set_config_value.assert_called_once_with("temperature", "")

    def test_temperature_in_config_keys(self):
        """Temperature should be in the list of config keys."""
        keys = cp_config.get_config_keys()
        assert "temperature" in keys


class TestModelSupportsSetting:
    """Tests for the model_supports_setting function."""

    @patch("code_muse.model_factory.ModelFactory.load_config")
    def test_returns_true_when_setting_in_supported_list(self, mock_load_config):
        """Should return True when setting is in supported_settings."""
        mock_load_config.return_value = {
            "test-model": {
                "type": "openai",
                "name": "test-model",
                "supported_settings": ["temperature", "seed"],
            }
        }
        assert cp_config.model_supports_setting("test-model", "temperature") is True
        assert cp_config.model_supports_setting("test-model", "seed") is True

    @patch("code_muse.model_factory.ModelFactory.load_config")
    def test_returns_false_when_setting_not_in_supported_list(self, mock_load_config):
        """Should return False when setting is not in supported_settings."""
        mock_load_config.return_value = {
            "test-model": {
                "type": "openai",
                "name": "test-model",
                "supported_settings": ["seed"],  # No temperature
            }
        }
        assert cp_config.model_supports_setting("test-model", "temperature") is False

    @patch("code_muse.model_factory.ModelFactory.load_config")
    def test_defaults_to_true_when_no_supported_settings(self, mock_load_config):
        """Should default to True for backwards compatibility."""
        mock_load_config.return_value = {
            "test-model": {
                "type": "openai",
                "name": "test-model",
                # No supported_settings field
            }
        }
        assert cp_config.model_supports_setting("test-model", "temperature") is True
        assert cp_config.model_supports_setting("test-model", "seed") is True

    @patch("code_muse.model_factory.ModelFactory.load_config")
    def test_returns_true_on_exception(self, mock_load_config):
        """Should return True when there's an exception loading config."""
        mock_load_config.side_effect = Exception("Config load failed")
        assert cp_config.model_supports_setting("test-model", "temperature") is True

    @patch("code_muse.model_factory.ModelFactory.load_config")
    def test_returns_true_for_unknown_model(self, mock_load_config):
        """Should default to True for unknown models."""
        mock_load_config.return_value = {}
        assert cp_config.model_supports_setting("unknown-model", "temperature") is True

    @patch("code_muse.model_factory.ModelFactory.load_config")
    def test_opus_46_fallback_supports_effort(self, mock_load_config):
        """Opus 4-6 models should support effort in the fallback path."""
        mock_load_config.return_value = {
            "claude-opus-4-6": {"type": "anthropic", "name": "claude-opus-4-6"}
        }
        assert cp_config.model_supports_setting("claude-opus-4-6", "effort") is True
        assert cp_config.model_supports_setting("claude-4-6-opus", "effort") is True

    @patch("code_muse.model_factory.ModelFactory.load_config")
    def test_non_opus_46_fallback_does_not_support_effort(self, mock_load_config):
        """Non Opus 4-6 Claude models should NOT support effort in fallback."""
        mock_load_config.return_value = {
            "claude-sonnet-4": {"type": "anthropic", "name": "claude-sonnet-4"}
        }
        assert cp_config.model_supports_setting("claude-sonnet-4", "effort") is False
