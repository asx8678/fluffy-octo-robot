"""Verbosity configuration for the filter engine.

Defines verbosity levels and provides helpers to read the current level
from CLI flags or the ``FAST_PUPPY_VERBOSITY`` environment variable.
"""

import os
import sys
from enum import IntEnum


class VerbosityLevel(IntEnum):
    """Verbosity levels for filter output compression.

    Attributes:
        ULTRA_COMPACT: Minimal output — single-line summaries only.
        COMPACT: Default — concise summaries with key counts.
        VERBOSE: Include file lists and short excerpts.
        VERY_VERBOSE: Include full output sections.
        RAW: Disable all filtering — passthrough raw output.
    """

    ULTRA_COMPACT = 0  # -u
    COMPACT = 1  # default (no flag)
    VERBOSE = 2  # -v
    VERY_VERBOSE = 3  # -vv
    RAW = 4  # -vvv


def get_verbosity() -> VerbosityLevel:
    """Determine the current verbosity level.

    Resolution order:

    1. Check ``sys.argv`` for ``-u``/``--ultra-compact``, ``-v``, ``-vv``, ``-vvv``.
    2. Check the ``FAST_PUPPY_VERBOSITY`` environment variable (``0``–``4``).
    3. Default to ``VerbosityLevel.COMPACT``.

    Returns:
        The resolved verbosity level.
    """
    # CLI flag parsing
    args = sys.argv
    if "-u" in args or "--ultra-compact" in args:
        return VerbosityLevel.ULTRA_COMPACT
    if "-vvv" in args:
        return VerbosityLevel.RAW
    if "-vv" in args:
        return VerbosityLevel.VERY_VERBOSE
    if "-v" in args:
        return VerbosityLevel.VERBOSE

    # Environment variable
    env_val = os.environ.get("FAST_PUPPY_VERBOSITY")
    if env_val is not None:
        try:
            level = int(env_val)
            if 0 <= level <= 4:
                return VerbosityLevel(level)
        except ValueError:
            pass

    return VerbosityLevel.COMPACT
