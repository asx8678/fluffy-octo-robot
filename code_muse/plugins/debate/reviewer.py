"""Reviewer LLM caller for the Debate Mode plugin.

Invokes a second LLM (the reviewer) with the planner's proposal and
returns a structured :class:`~code_muse.plugins.debate.schemas.Verdict`.

The actual LLM integration is implemented in Phase 2; this module
provides the public interface and a placeholder implementation.
"""

import logging

from code_muse.plugins.debate.schemas import ReviewRequest, ReviewResponse, Verdict

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def run_review(request: ReviewRequest) -> ReviewResponse | None:
    """Call the reviewer LLM and return a structured verdict.

    Args:
        request: The planner's proposal and reasoning summary.

    Returns:
        A :class:`ReviewResponse` with the verdict, or ``None`` if the
        reviewer could not be reached.

    .. note:: Phase 2 implements the actual LLM call.  This scaffold
       returns a placeholder approval so the hook/tool wiring can be
       tested end-to-end.
    """
    logger.info(
        "Review requested at checkpoint %d "
        "(placeholder — Phase 2 will implement LLM call)",
        request.checkpoint,
    )

    # Placeholder: always approve.  Phase 2 replaces this with a real
    # reviewer call using the reviewer_system prompt and a second model.
    verdict = Verdict(
        kind="approve",
        summary="Placeholder approval — Phase 2 will provide real review.",
    )

    from code_muse.plugins.debate.state import DebateState

    DebateState.record_review(request.checkpoint, verdict.kind)

    return ReviewResponse(
        verdict=verdict,
        review_count=DebateState.review_count(),
        remaining_budget=DebateState.remaining_budget(),
    )
