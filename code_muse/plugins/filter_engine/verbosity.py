"""Verbosity configuration for the filter engine.

Defines verbosity levels and provides helpers to read the current level
from a CLI-set override or the ``FAST_PUPPY_VERBOSITY`` environment variable.
"""

import os
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

    ULTRA_COMPACT = 0  # --ultra-compact
    COMPACT = 1  # default (no flag)
    VERBOSE = 2  # --verbose
    VERY_VERBOSE = 3  # --verbose --verbose (or -vv)
    RAW = 4  # --verbose --verbose --verbose (or -vvv)


# Module-level override set by CLI after argparse (avoids sys.argv scan).
_verbosity_override: VerbosityLevel | None = None


def set_verbosity(level: VerbosityLevel) -> None:
    """Set a process-wide verbosity override.

    Called by the CLI entry point after ``argparse`` parses ``--verbose``
    or ``--ultra-compact`` flags.  Overrides the environment variable but
    can itself be overridden by passing an explicit argument to
    :func:`get_verbosity`.
    """
    global _verbosity_override
    _verbosity_override = level


def get_verbosity(verbosity: VerbosityLevel | None = None) -> VerbosityLevel:
    """Determine the current verbosity level.

    Resolution order:

    1. Explicit *verbosity* argument (passed by callers that already know).
    2. CLI-set override (via :func:`set_verbosity`, called after argparse).
    3. ``FAST_PUPPY_VERBOSITY`` environment variable (``0``–``4``).
    4. Default to :attr:`VerbosityLevel.COMPACT`.

    Args:
        verbosity: Optional explicit level.  When ``None`` (the default)
            the resolution chain above is used.

    Returns:
        The resolved verbosity level.
    """
    if verbosity is not None:
        return verbosity

    global _verbosity_override
    if _verbosity_override is not None:
        return _verbosity_override

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
