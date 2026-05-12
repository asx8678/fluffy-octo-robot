"""Detect the boundary between static (cacheable) prefix and dynamic suffix."""


def detect_cache_breakpoint(messages: list[dict]) -> int:
    """Find the boundary between static prefix and dynamic suffix.

    Heuristic: everything before the first user message is static
    (system prompt, project context, etc.). Returns the index of the
    last static message (the breakpoint).

    Args:
        messages: Anthropic-style message list with ``role`` keys.

    Returns:
        Index of the last static message, or 0 if there is no static
        prefix, or ``len(messages) - 1`` if every message is static.
    """
    if not messages:
        return 0

    for idx, msg in enumerate(messages):
        if isinstance(msg, dict) and msg.get("role") == "user":
            # First user message found — everything before it is static.
            # The breakpoint is the message just before this one.
            return max(0, idx - 1)

    # No user message found — treat everything as static.
    return len(messages) - 1
