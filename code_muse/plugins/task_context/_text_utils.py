"""Shared text extraction utilities for the task_context plugin.

Centralises the _extract_text() helper to eliminate duplication across
detector, scorer, pruner, and archival modules.
"""

from typing import Any


def _extract_text(message: Any) -> str:
    """Extract plain text content from various message formats.

    Handles pydantic-ai ModelMessage, dict messages, and plain strings.
    """
    if isinstance(message, str):
        return message
    if isinstance(message, dict):
        # Try common dict formats
        for key in ("content", "text", "message", "parts", "user_message"):
            val = message.get(key)
            if isinstance(val, str):
                return val
        return ""
    # pydantic-ai ModelMessage
    try:
        parts = getattr(message, "parts", []) or []
        texts: list[str] = []
        for part in parts:
            content = getattr(part, "content", None)
            if isinstance(content, str):
                texts.append(content)
            elif isinstance(content, list):
                for item in content:
                    if isinstance(item, str):
                        texts.append(item)
        return " ".join(texts)
    except Exception:
        return str(message) if message else ""
