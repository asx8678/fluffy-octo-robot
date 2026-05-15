from unittest.mock import patch

from code_muse.config import (
    get_compaction_strategy,
)
from code_muse.config.parser import set_config_value


def test_default_compaction_strategy():
    """Test that the default compaction strategy is summarization (modern default)"""
    with patch("code_muse.config.get_value") as mock_get_value:
        mock_get_value.return_value = None
        strategy = get_compaction_strategy()
        assert strategy == "summarization"


def test_set_compaction_strategy_truncation():
    """Test that we can set the compaction strategy to truncation"""
    set_config_value("compaction_strategy", "truncation")
    strategy = get_compaction_strategy()
    assert strategy == "truncation"


def test_set_compaction_strategy_summarization():
    """Test that we can set the compaction strategy to summarization"""
    set_config_value("compaction_strategy", "summarization")
    strategy = get_compaction_strategy()
    assert strategy == "summarization"


def test_set_compaction_strategy_invalid():
    """Test that an invalid compaction strategy defaults to summarization"""
    set_config_value("compaction_strategy", "invalid_strategy")
    strategy = get_compaction_strategy()
    assert strategy == "summarization"
