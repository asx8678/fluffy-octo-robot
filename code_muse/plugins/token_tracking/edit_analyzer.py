"""Edit context inflation analyzer — ported from Pi project.

Measures how much wrapper/boilerplate code surrounds the actual change
in file edit operations, revealing token waste.
"""


def _utf8_bytes(text: str) -> int:
    """Count UTF-8 bytes in a string."""
    return len(text.encode("utf-8"))


def _longest_common_prefix_len(a: str, b: str) -> int:
    """Length of the longest common prefix between two strings."""
    max_len = min(len(a), len(b))
    i = 0
    while i < max_len and a[i] == b[i]:
        i += 1
    return i


def _longest_common_suffix_len(a: str, b: str) -> int:
    """Length of the longest common suffix between two strings."""
    max_len = min(len(a), len(b))
    i = 0
    while i < max_len and a[-(i + 1)] == b[-(i + 1)]:
        i += 1
    return i


def analyze_replacement(
    old_text: str,
    new_text: str,
) -> dict:
    """Analyze an old→new text replacement for context inflation.

    Returns a dict with byte-level metrics:
    - old_bytes, new_bytes: raw UTF-8 byte counts
    - total_edit_bytes: old + new
    - shared_prefix_bytes, shared_suffix_bytes: identical wrapper context
    - shared_context_bytes: prefix + suffix
    - core_old_bytes, core_new_bytes: the actual changed portions
    - core_bytes: core_old + core_new (the meaningful change)
    - wrapper_payload_bytes: total - core (the overhead)
    - inflation_ratio: total / core (None if no core change)
    - no_core_change: True when old == new (pure wrapper churn)
    """
    old_bytes = _utf8_bytes(old_text)
    new_bytes = _utf8_bytes(new_text)
    total = old_bytes + new_bytes

    prefix_chars = _longest_common_prefix_len(old_text, new_text)
    old_remainder = old_text[prefix_chars:]
    new_remainder = new_text[prefix_chars:]

    suffix_chars = _longest_common_suffix_len(old_remainder, new_remainder)

    old_core = (
        old_remainder[: len(old_remainder) - suffix_chars]
        if suffix_chars > 0
        else old_remainder
    )
    new_core = (
        new_remainder[: len(new_remainder) - suffix_chars]
        if suffix_chars > 0
        else new_remainder
    )

    prefix = old_text[:prefix_chars]
    suffix = old_remainder[-suffix_chars:] if suffix_chars > 0 else ""

    shared_prefix_bytes = _utf8_bytes(prefix)
    shared_suffix_bytes = _utf8_bytes(suffix)
    shared_context_bytes = shared_prefix_bytes + shared_suffix_bytes

    core_old_bytes = _utf8_bytes(old_core)
    core_new_bytes = _utf8_bytes(new_core)
    core_bytes = core_old_bytes + core_new_bytes
    wrapper_payload_bytes = total - core_bytes

    no_core_change = core_bytes == 0
    inflation_ratio = None if no_core_change else total / core_bytes

    return {
        "old_bytes": old_bytes,
        "new_bytes": new_bytes,
        "total_edit_bytes": total,
        "shared_prefix_bytes": shared_prefix_bytes,
        "shared_suffix_bytes": shared_suffix_bytes,
        "shared_context_bytes": shared_context_bytes,
        "core_old_bytes": core_old_bytes,
        "core_new_bytes": core_new_bytes,
        "core_bytes": core_bytes,
        "wrapper_payload_bytes": wrapper_payload_bytes,
        "inflation_ratio": inflation_ratio,
        "no_core_change": no_core_change,
    }
