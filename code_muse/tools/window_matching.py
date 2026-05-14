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

    Performance: pre-joins haystack once and uses string slicing
    instead of per-iteration join, reducing O(n) allocations to O(1).
    """
    needle = needle.rstrip("\n")
    needle_lines = needle.splitlines()
    win_size = len(needle_lines)

    if win_size == 0:
        return (None, 0.0)

    best_score = 0.0
    best_span: tuple[int, int | None] = None

    n_haystack = len(haystack_lines)
    # Short-circuit: haystack smaller than needle
    if n_haystack < win_size:
        return (None, 0.0)

    # Pre-join haystack once — O(n) allocation instead of O(n) per iteration
    joined_haystack = "\n".join(haystack_lines)

    # Build line offset index: offsets[i] = char position of line i start
    offsets = [0]
    for line in haystack_lines:
        offsets.append(offsets[-1] + len(line) + 1)  # +1 for newline

    for i in range(n_haystack - win_size + 1):
        # String slice instead of "\n".join(list_slice) — no allocation
        start = offsets[i]
        end = offsets[i + win_size] - 1  # exclude trailing newline
        window = joined_haystack[start:end]
        score = _jaro_winkler_similarity(window, needle)

        if score > best_score:
            best_score = score
            best_span = (i, i + win_size)
            # Early termination: near-perfect match found
            if score > 0.95:
                break

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
