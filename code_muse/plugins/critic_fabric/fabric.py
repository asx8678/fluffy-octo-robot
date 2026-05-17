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

import hashlib
import logging

from code_muse.plugins.critic_fabric.backends import get_backend
from code_muse.plugins.critic_fabric.cache import get_review_cache
from code_muse.plugins.critic_fabric.models import (
    CriticRequest,
    CriticVerdict,
    VerdictKind,
)
from code_muse.plugins.critic_fabric.preflight import run_preflight

logger = logging.getLogger(__name__)


def _compute_content_hash(file_path: str, code_snippet: str) -> str:
    """Deterministic 16-char hash of file_path + code content."""
    raw = f"{file_path}::{code_snippet}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _compute_review_hash(content_hash: str, reviewer_id: str) -> str:
    """Deterministic 16-char hash of content_hash + reviewer."""
    raw = f"{content_hash}::{reviewer_id}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


async def review(request: CriticRequest) -> CriticVerdict:
    """Run a full critic review: cache → preflight → backend.

    1. Compute ``content_hash`` and check the review cache.
       If a cached verdict exists, return it immediately.
    2. Run preflight (truncation / structural checks).
       If truncated, return a rejected verdict — stamped with hashes.
    3. Resolve the requested backend (with alias support).
    4. Call the backend, stamp provenance, cache the result.
    5. On any unexpected error, return a safe ``error`` verdict.

    Args:
        request: A ``CriticRequest`` describing what to review.

    Returns:
        A ``CriticVerdict`` with the review outcome.
    """
    # --- Compute content_hash ---
    content_hash = _compute_content_hash(request.file_path, request.code_snippet)
    reviewer_id = request.backend  # backend name as default reviewer_id

    # --- Cache check ---
    cached = get_review_cache().get(content_hash, reviewer_id)
    if cached is not None:
        logger.debug(
            "Cache HIT for %s (hash=%s)",
            request.file_path,
            content_hash[:8],
        )
        verdict = CriticVerdict.from_dict(cached, backend=request.backend)
        if not verdict.summary:
            verdict.summary = "(cached)"
        return verdict

    logger.debug(
        "Cache MISS for %s (hash=%s)",
        request.file_path,
        content_hash[:8],
    )

    # --- Preflight gate ---
    preflight_result = run_preflight(request.code_snippet, request.file_path)
    if preflight_result is not None:
        logger.debug(
            "Preflight rejected %s — skipping backend '%s'",
            request.file_path,
            request.backend,
        )
        # Stamp provenance on preflight rejections
        review_hash = _compute_review_hash(content_hash, reviewer_id)
        preflight_result.content_hash = content_hash
        preflight_result.reviewer_id = reviewer_id
        preflight_result.review_hash = review_hash
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
            verdict.backend = request.backend

        # Stamp provenance fields
        review_hash = _compute_review_hash(content_hash, reviewer_id)
        verdict.content_hash = content_hash
        verdict.reviewer_id = reviewer_id
        verdict.review_hash = review_hash

        # Cache the verdict (serialise to dict for safety)
        get_review_cache().set(content_hash, verdict.to_dict(), reviewer_id)

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
