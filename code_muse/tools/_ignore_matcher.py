"""Fast path-matching for file ignore patterns."""

import fnmatch
from pathlib import Path

from code_muse.tools._patterns import DIR_IGNORE_PATTERNS, IGNORE_PATTERNS


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
                subpath_str = str(subpath)
                if fnmatch.fnmatch(subpath_str, simplified_pattern):
                    return True
                if fnmatch.fnmatch(path_parts[i], simplified_pattern):
                    return True

    return False


def should_ignore_dir_path(path: str) -> bool:
    """Return True if path matches any directory ignore pattern (directories only)."""
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
                subpath_str = str(subpath)
                if fnmatch.fnmatch(subpath_str, simplified):
                    return True
                if fnmatch.fnmatch(parts[i], simplified):
                    return True
    return False
