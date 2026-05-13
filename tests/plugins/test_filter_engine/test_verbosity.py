"""Tests for verbosity configuration."""

import sys
from unittest.mock import patch

from code_muse.plugins.filter_engine.verbosity import VerbosityLevel, get_verbosity, set_verbosity


class TestVerbosityDefaults:
    """Default and environment-based verbosity."""

    def test_default_is_compact(self) -> None:
        with patch.object(sys, "argv", ["code_muse"]):
            with patch.dict("os.environ", {}, clear=True):
                assert get_verbosity() == VerbosityLevel.COMPACT

    def test_env_var_parsing(self) -> None:
        for level in range(5):
            with patch.object(sys, "argv", ["code_muse"]):
                with patch.dict("os.environ", {"FAST_PUPPY_VERBOSITY": str(level)}):
                    assert get_verbosity() == VerbosityLevel(level)

    def test_invalid_env_var_ignored(self) -> None:
        with patch.object(sys, "argv", ["code_muse"]):
            with patch.dict("os.environ", {"FAST_PUPPY_VERBOSITY": "banana"}):
                assert get_verbosity() == VerbosityLevel.COMPACT

    def test_out_of_range_env_var_ignored(self) -> None:
        with patch.object(sys, "argv", ["code_muse"]):
            with patch.dict("os.environ", {"FAST_PUPPY_VERBOSITY": "99"}):
                assert get_verbosity() == VerbosityLevel.COMPACT


class TestVerbosityCliFlags:
    """CLI flag parsing."""

    def test_ultra_compact_flag(self) -> None:
        set_verbosity(VerbosityLevel.ULTRA_COMPACT)
        with patch.dict("os.environ", {}, clear=True):
            assert get_verbosity() == VerbosityLevel.ULTRA_COMPACT
        set_verbosity(VerbosityLevel.COMPACT)  # reset

    def test_ultra_compact_long_flag(self) -> None:
        set_verbosity(VerbosityLevel.ULTRA_COMPACT)
        with patch.dict("os.environ", {}, clear=True):
            assert get_verbosity() == VerbosityLevel.ULTRA_COMPACT
        set_verbosity(VerbosityLevel.COMPACT)  # reset

    def test_verbose_flag(self) -> None:
        set_verbosity(VerbosityLevel.VERBOSE)
        with patch.dict("os.environ", {}, clear=True):
            assert get_verbosity() == VerbosityLevel.VERBOSE
        set_verbosity(VerbosityLevel.COMPACT)  # reset

    def test_very_verbose_flag(self) -> None:
        set_verbosity(VerbosityLevel.VERY_VERBOSE)
        with patch.dict("os.environ", {}, clear=True):
            assert get_verbosity() == VerbosityLevel.VERY_VERBOSE
        set_verbosity(VerbosityLevel.COMPACT)  # reset

    def test_raw_flag(self) -> None:
        set_verbosity(VerbosityLevel.RAW)
        with patch.dict("os.environ", {}, clear=True):
            assert get_verbosity() == VerbosityLevel.RAW
        set_verbosity(VerbosityLevel.COMPACT)  # reset

    def test_flags_override_env(self) -> None:
        set_verbosity(VerbosityLevel.ULTRA_COMPACT)
        with patch.dict("os.environ", {"FAST_PUPPY_VERBOSITY": "4"}):
            assert get_verbosity() == VerbosityLevel.ULTRA_COMPACT
        set_verbosity(VerbosityLevel.COMPACT)  # reset

