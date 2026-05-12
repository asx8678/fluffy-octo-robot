import configparser
import tempfile
from pathlib import Path
from unittest.mock import patch

from code_muse.config import (
    DEFAULT_SECTION,
    get_compaction_strategy,
)


def test_default_compaction_strategy():
    """Test that the default compaction strategy is truncation"""
    with patch("code_muse.config.get_value") as mock_get_value:
        mock_get_value.return_value = None
        strategy = get_compaction_strategy()
        assert strategy == "truncation"


def test_set_compaction_strategy_truncation():
    """Test that we can set the compaction strategy to truncation"""
    import code_muse.config

    original_config_dir = code_muse.config.CONFIG_DIR
    original_config_file = code_muse.config.CONFIG_FILE

    with tempfile.TemporaryDirectory() as temp_dir:
        try:
            code_muse.config.CONFIG_DIR = temp_dir
            code_muse.config.CONFIG_FILE = Path(temp_dir) / "muse.cfg"

            config = configparser.ConfigParser()
            config[DEFAULT_SECTION] = {}
            config[DEFAULT_SECTION]["compaction_strategy"] = "truncation"

            with open(code_muse.config.CONFIG_FILE, "w") as f:
                config.write(f)

            strategy = get_compaction_strategy()
            assert strategy == "truncation"
        finally:
            code_muse.config.CONFIG_DIR = original_config_dir
            code_muse.config.CONFIG_FILE = original_config_file


def test_set_compaction_strategy_summarization():
    """Test that we can set the compaction strategy to summarization"""
    import code_muse.config

    original_config_dir = code_muse.config.CONFIG_DIR
    original_config_file = code_muse.config.CONFIG_FILE

    with tempfile.TemporaryDirectory() as temp_dir:
        try:
            code_muse.config.CONFIG_DIR = temp_dir
            code_muse.config.CONFIG_FILE = Path(temp_dir) / "muse.cfg"

            config = configparser.ConfigParser()
            config[DEFAULT_SECTION] = {}
            config[DEFAULT_SECTION]["compaction_strategy"] = "summarization"

            with open(code_muse.config.CONFIG_FILE, "w") as f:
                config.write(f)

            strategy = get_compaction_strategy()
            assert strategy == "summarization"
        finally:
            code_muse.config.CONFIG_DIR = original_config_dir
            code_muse.config.CONFIG_FILE = original_config_file


def test_set_compaction_strategy_invalid():
    """Test that an invalid compaction strategy defaults to truncation"""
    import code_muse.config

    original_config_dir = code_muse.config.CONFIG_DIR
    original_config_file = code_muse.config.CONFIG_FILE

    with tempfile.TemporaryDirectory() as temp_dir:
        try:
            code_muse.config.CONFIG_DIR = temp_dir
            code_muse.config.CONFIG_FILE = Path(temp_dir) / "muse.cfg"

            config = configparser.ConfigParser()
            config[DEFAULT_SECTION] = {}
            config[DEFAULT_SECTION]["compaction_strategy"] = "invalid_strategy"

            with open(code_muse.config.CONFIG_FILE, "w") as f:
                config.write(f)

            strategy = get_compaction_strategy()
            assert strategy == "truncation"
        finally:
            code_muse.config.CONFIG_DIR = original_config_dir
            code_muse.config.CONFIG_FILE = original_config_file
