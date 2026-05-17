"""Preflight checks — truncation and structural sanity *before* any LLM call.

This is the canonical place for pre-LLM checks.  It delegates to the
proven ``truncation_detector.detect_truncation`` function and translates
the result into a ``CriticVerdict`` with ``preflight_rejected=True``.

Callers should invoke ``run_preflight()`` and check the return value:

- If the result is a ``CriticVerdict`` (not ``None``), the code is
  truncated / invalid — **do not** invoke any backend.
- If the result is ``None``, the code passed preflight — proceed to the
  chosen backend.

This design keeps the preflight logic testable in isolation without
requiring any LLM or backend machinery.
"""

from __future__ import annotations

import logging

from code_muse.plugins.critic_fabric.models import CriticVerdict, VerdictKind
from code_muse.plugins.truncation_detector.detector import detect_truncation

logger = logging.getLogger(__name__)


def run_preflight(code: str, file_path: str) -> CriticVerdict | None:
    """Run pre-LLM sanity checks on *code*.

    Returns a rejected ``CriticVerdict`` when the code is truncated or
    structurally invalid, or ``None`` when the code looks OK and a
    backend review should proceed.

    Args:
        code: The code content to check.
        file_path: File path hint (used for AST detection on ``.py``).

    Returns:
        A ``CriticVerdict`` with ``preflight_rejected=True`` on failure,
        or ``None`` when preflight passes.
    """
    result = detect_truncation(code, file_path=file_path)

    if not result.is_truncated:
        return None

    # Build a deterministic rejected verdict
    reason = result.reason or "Code appears truncated or structurally invalid"
    issues = [reason]

    # Add contextual guidance based on detection method
    suggestion = _suggestion_for_method(result.method, file_path)

    logger.debug(
        "Preflight rejected %s: [%s] %s",
        file_path,
        result.method,
        reason,
    )

    return CriticVerdict(
        verdict=VerdictKind.REJECTED,
        summary="Code appears syntactically truncated or incomplete",
        issues=issues,
        suggestion=suggestion,
        backend="preflight",
        preflight_rejected=True,
    )


def _suggestion_for_method(method: str | None, file_path: str) -> str:
    """Return a contextual rewrite suggestion based on the detection method."""
    if method == "ast_parse" or file_path.endswith((".py", ".pyi")):
        return (
            "Rewrite the ENTIRE file in one response. "
            "Output complete Python that parses with ast.parse()."
        )
    return (
        "Rewrite the ENTIRE file in one response. "
        "Output the complete, valid source for the whole file."
    )
