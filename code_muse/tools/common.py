"""Shared tool utilities (ignore patterns, browser suppression, re-exports)."""

import os

from rich.console import Console

NO_COLOR = bool(int(os.environ.get("MUSE_NO_COLOR", "0")))
console = Console(no_color=NO_COLOR)

# Re-exports from extracted submodules for backward compatibility
from code_muse.tools.diff_formatting import (  # noqa: E402,F401
    _extract_file_extension_from_diff,
    _format_diff_with_syntax_highlighting,
    _get_lexer_for_extension,
    _get_token_color,
    _highlight_code_line,
    brighten_hex,
    format_diff_with_colors,
)
from code_muse.tools.user_interaction import (  # noqa: E402,F401
    arrow_select,
    arrow_select_async,
    get_user_approval,
    get_user_approval_async,
)
from code_muse.tools.window_matching import (  # noqa: E402,F401
    _find_best_window,
    _jaro_winkler_similarity,
    generate_group_id,
)


def should_suppress_browser() -> bool:
    """Check if browsers should be suppressed (headless mode).

    Returns:
        True if browsers should be suppressed, False if they can open normally

    This respects multiple headless mode controls:
    - HEADLESS=true environment variable (suppresses ALL browsers)
    - BROWSER_HEADLESS=true environment variable (for browser automation)
    - CI=true environment variable (continuous integration)
    - PYTEST_CURRENT_TEST environment variable (running under pytest)
    """
    # Explicit headless mode
    if os.getenv("HEADLESS", "").lower() == "true":
        return True

    # Browser-specific headless mode
    if os.getenv("BROWSER_HEADLESS", "").lower() == "true":
        return True

    # Continuous integration environments
    if os.getenv("CI", "").lower() == "true":
        return True

    # Default to allowing browsers
    return "PYTEST_CURRENT_TEST" in os.environ


# -------------------
# Shared ignore patterns/helpers
# Patterns live in _patterns.py so both this module and _ignore_matcher
# can import them without creating circular dependencies.
# -------------------
from code_muse.tools._ignore_matcher import (  # noqa: E402,F401 — re-exported for backward compat
    should_ignore_dir_path,
    should_ignore_path,
)
from code_muse.tools._patterns import (  # noqa: E402,F401 — re-exported for backward compat
    DIR_IGNORE_PATTERNS,
    FILE_IGNORE_PATTERNS,
    IGNORE_PATTERNS,
)


# ============================================================================
