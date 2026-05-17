"""Helpers for lightweight case-insensitive list filtering in TUIs.

Compiled with Cython for faster hot-path execution.
"""

import re

_NON_ALNUM_RE = re.compile(r"[^0-9a-z]+")


cpdef str normalize_filter_text(str text):
    """Normalize text for forgiving case-insensitive substring matching."""
    cdef str normalized = _NON_ALNUM_RE.sub(" ", text.casefold()).strip()
    return " ".join(normalized.split())


def query_matches_text(query: str, *candidates: str) -> bool:
    """Return True when every query term appears in the candidate text.

    Note: uses ``def`` instead of ``cpdef`` because Cython cpdef
    functions cannot accept ``*args`` varargs.
    """
    cdef list terms = normalize_filter_text(query).split()
    if not terms:
        return True

    cdef str haystack = " ".join(
        normalize_filter_text(candidate) for candidate in candidates if candidate
    ).strip()
    if not haystack:
        return False

    cdef str term
    for term in terms:
        if term not in haystack:
            return False
    return True
