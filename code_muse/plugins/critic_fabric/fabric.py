"""Critic Fabric — top-level review orchestrator.

This is the single entry-point that all critic consumers should use:

    verdict = await review(request)

It runs preflight checks first (truncation / structural sanity) and
short-circuits with a rejected ``CriticVerdict`` before any LLM call
when the input is obviously truncated or invalid.

If preflight passes, it delegates to the requested backend (resolved
via the backend registry in ``backends.py``).
"""

from __future__ import annotations

import logging

from code_muse.plugins.critic_fabric.backends import get_backend
from code_muse.plugins.critic_fabric.models import (
    CriticRequest,
    CriticVerdict,
    VerdictKind,
)
from code_muse.plugins.critic_fabric.preflight import run_preflight

logger = logging.getLogger(__name__)


async def review(request: CriticRequest) -> CriticVerdict:
    """Run a full critic review: preflight → backend.

    1. Run preflight (truncation / structural checks).
       If truncated, return a rejected verdict immediately — no backend called.
    2. Resolve the requested backend (with alias support).
    3. Call the backend and return its verdict.
    4. On any unexpected error, return a safe ``error`` verdict.

    Args:
        request: A ``CriticRequest`` describing what to review.

    Returns:
        A ``CriticVerdict`` with the review outcome.
    """
    # --- Preflight gate ---
    preflight_result = run_preflight(request.code_snippet, request.file_path)
    if preflight_result is not None:
        logger.debug(
            "Preflight rejected %s — skipping backend '%s'",
            request.file_path,
            request.backend,
        )
        return preflight_result

    # --- Backend dispatch ---
    try:
        backend_func = get_backend(request.backend)
    except KeyError as exc:
        logger.error("Backend resolution failed: %s", exc)
        return CriticVerdict(
            verdict=VerdictKind.ERROR,
            summary=str(exc),
            issues=[str(exc)],
            backend=request.backend,
        )

    try:
        verdict = await backend_func(request)
        # Stamp the backend name if the backend didn't set it
        if not verdict.backend:
            verdict = verdict.model_copy(update={"backend": request.backend})
        return verdict
    except Exception as exc:
        logger.error(
            "Backend '%s' raised for %s: %s",
            request.backend,
            request.file_path,
            exc,
            exc_info=True,
        )
        return CriticVerdict(
            verdict=VerdictKind.ERROR,
            summary=f"Backend '{request.backend}' failed: {exc}",
            issues=[f"Review error: {exc}"],
            suggestion="Manual review recommended.",
            backend=request.backend,
        )
