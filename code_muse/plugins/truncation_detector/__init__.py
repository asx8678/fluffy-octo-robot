"""Truncation Detector plugin for Muse — pre-LLM truncation detection.

Provides the ``detect_truncation`` and ``is_truncated`` functions for
identifying obviously truncated code output **before** any LLM critic
call is made.  Other plugins import these as their standard truncation
check.

Architecture
------------

- ``detector.py`` — Pure detection engine (no hooks, no state, independently testable)
- ``register_callbacks.py`` — Hook registration, metric emission, slash commands

Key Design Decisions
--------------------

1. Detection is a pure function — no I/O, no state, no side effects.
2. Runs at ``pre_tool_call`` to block critic LLM calls on truncated code.
3. Runs at ``post_tool_call`` to flag truncated file writes for observability.
4. Zero false positives required — only flag definitely truncated output.
5. Emits ``truncation_detected`` events to the upgrade_metrics system.
"""

from code_muse.plugins.truncation_detector.detector import (
    TruncationResult,
    detect_truncation,
    is_truncated,
)

__all__ = [
    "TruncationResult",
    "detect_truncation",
    "is_truncated",
]
