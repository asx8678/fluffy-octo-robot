"""Shared utilities for the Gemini model implementation."""

import uuid


def generate_tool_call_id() -> str:
    """Generate a unique tool call ID."""
    return str(uuid.uuid4())
