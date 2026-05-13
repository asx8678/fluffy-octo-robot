"""Fuzzy window matching and unique ID generation helpers."""

import hashlib
import time
from pathlib import Path

from rapidfuzz.distance import JaroWinkler


def _jaro_winkler_similarity(s1: str, s2: str) -> float:
    """Jaro-Winkler similarity with LRU cache for repeated comparisons."""
    return JaroWinkler.normalized_similarity(s1, s2)


def _find_best_window(
    haystack_lines: list[str],
    needle: str,
) -> tuple[tuple[int, int | None], float]:
    """
    Return (start, end) indices of the window with the highest
    Jaro-Winkler similarity to `needle`, along with that score.
    If nothing clears JW_THRESHOLD, return (None, score).
    """
    needle = needle.rstrip("\n")
    needle_lines = needle.splitlines()
    win_size = len(needle_lines)
    best_score = 0.0
    best_span: tuple[int, int | None] = None
    # Pre-join the needle once; join windows on the fly
    for i in range(len(haystack_lines) - win_size + 1):
        window = "\n".join(haystack_lines[i : i + win_size])
        score = _jaro_winkler_similarity(window, needle)
        if score > best_score:
            best_score = score
            best_span = (i, i + win_size)

    return best_span, best_score


def generate_group_id(tool_name: str, extra_context: str | Path = "") -> str:
    """Generate a unique group_id for tool output grouping.

    Args:
        tool_name: Name of the tool (e.g., 'list_files', 'edit_file')
        extra_context: Optional extra context to make group_id more unique

    Returns:
        A string in format: tool_name_hash
    """
    # Create a unique identifier using timestamp, context, and a random component
    import random

    timestamp = str(int(time.time() * 1000000))  # microseconds for more uniqueness
    random_component = random.randint(1000, 9999)  # Add randomness
    context_string = f"{tool_name}_{timestamp}_{random_component}_{extra_context}"

    # Generate a short hash
    hash_obj = hashlib.blake2b(context_string.encode(), digest_size=16)
    short_hash = hash_obj.hexdigest()[:8]

    return f"{tool_name}_{short_hash}"
