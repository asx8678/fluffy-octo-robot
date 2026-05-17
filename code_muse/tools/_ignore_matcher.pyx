"""Fast path-matching for file ignore patterns. Compiled with Cython."""

from pathlib import Path
import fnmatch

from code_muse.tools._patterns import IGNORE_PATTERNS, DIR_IGNORE_PATTERNS


cpdef bint should_ignore_path(str path):
    """Return True if *path* matches any pattern in IGNORE_PATTERNS."""
    cdef str pattern
    cdef str simplified_pattern
    cdef str subpath_str
    cdef str part
    cdef int i

    path_obj = Path(path)

    for pattern in IGNORE_PATTERNS:
        # Try pathlib's match method which handles ** patterns properly
        try:
            if path_obj.match(pattern):
                return True
        except ValueError:
            # If pathlib can't handle the pattern, fall back to fnmatch
            if fnmatch.fnmatch(path, pattern):
                return True

        # Additional check: if pattern contains **, try matching against
        # different parts of the path to handle edge cases
        if "**" in pattern:
            simplified_pattern = pattern.replace("**/", "").replace("/**", "")
            path_parts = path_obj.parts
            for i in range(len(path_parts)):
                subpath = Path(*path_parts[i:])
                subpath_str = str(subpath)
                if fnmatch.fnmatch(subpath_str, simplified_pattern):
                    return True
                # Also check individual parts
                if fnmatch.fnmatch(path_parts[i], simplified_pattern):
                    return True

    return False


cpdef bint should_ignore_dir_path(str path):
    """Return True if path matches any directory ignore pattern (directories only)."""
    cdef str pattern
    cdef str simplified
    cdef str subpath_str
    cdef str part
    cdef int i

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
