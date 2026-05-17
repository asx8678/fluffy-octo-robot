"""Shared tool utilities (ignore patterns, browser suppression, re-exports)."""

import fnmatch
import os
from pathlib import Path

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
# Patterns live in _patterns.py so both this module and the Cython-compiled
# _ignore_matcher can import them without creating circular dependencies.
# -------------------
from code_muse.tools._patterns import (  # noqa: F401 — re-exported for backward compat
    DIR_IGNORE_PATTERNS,
    FILE_IGNORE_PATTERNS,
    IGNORE_PATTERNS,
)


# Try to use the compiled Cython implementation for hot-path performance;
# fall back to a pure-Python reimplementation if Cython extensions are absent.
try:
    from code_muse.tools._ignore_matcher import (
        should_ignore_path as _compiled_should_ignore_path,
        should_ignore_dir_path as _compiled_should_ignore_dir_path,
    )

    def should_ignore_path(path: str) -> bool:
        """Return True if *path* matches any pattern in IGNORE_PATTERNS."""
        return _compiled_should_ignore_path(path)

    def should_ignore_dir_path(path: str) -> bool:
        """Return True if path matches any directory ignore pattern (directories only)."""
        return _compiled_should_ignore_dir_path(path)

except ImportError:

    def should_ignore_path(path: str) -> bool:
        """Return True if *path* matches any pattern in IGNORE_PATTERNS."""
        path_obj = Path(path)

        for pattern in IGNORE_PATTERNS:
            try:
                if path_obj.match(pattern):
                    return True
            except ValueError:
                if fnmatch.fnmatch(path, pattern):
                    return True

            if "**" in pattern:
                simplified_pattern = pattern.replace("**/", "").replace("/**", "")
                path_parts = path_obj.parts
                for i in range(len(path_parts)):
                    subpath = Path(*path_parts[i:])
                    if fnmatch.fnmatch(str(subpath), simplified_pattern):
                        return True
                    if fnmatch.fnmatch(path_parts[i], simplified_pattern):
                        return True

        return False

    def should_ignore_dir_path(path: str) -> bool:
        """Return True if path matches any directory ignore pattern."""
        path_obj = Path(path)
        for pattern in DIR_IGNORE_PATTERNS:
            try:
                if path_obj.match(pattern):
                    return True
            except ValueError:
                if fnmatch.fnmatch(path, pattern):
                    return True
            if "**" in pattern:
                simplified = pattern.replace("**/", "").replace("/**", "")
                parts = path_obj.parts
                for i in range(len(parts)):
                    subpath = Path(*parts[i:])
                    if fnmatch.fnmatch(str(subpath), simplified):
                        return True
                    if fnmatch.fnmatch(parts[i], simplified):
                        return True
        return False


# ============================================================================
