"""Reviewer LLM caller for the Debate Mode plugin.

Invokes a second LLM (the reviewer) with the planner's proposal and
returns a structured :class:`~code_muse.plugins.debate.schemas.Verdict`.

The reviewer is a pydantic-ai Agent with no tools — it receives the
reviewer system prompt and the planner's proposal as user text, then
returns structured JSON that we parse into a :class:`Verdict`.
"""

import logging
import re
from pathlib import Path

import orjson as json

from code_muse.plugins.debate.config import (
    get_debate_reviewer_model,
    is_debate_enabled,
)
from code_muse.plugins.debate.schemas import (
    Issue,
    ReviewRequest,
    ReviewResponse,
    Verdict,
    VerdictKind,
)
from code_muse.plugins.debate.state import DebateState

logger = logging.getLogger(__name__)

# Path to the reviewer system prompt bundled with this plugin
_PROMPTS_DIR = Path(__file__).parent / "prompts"


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------


def _load_reviewer_system_prompt() -> str:
    """Load the reviewer system prompt from the prompts directory."""
    path = _PROMPTS_DIR / "reviewer_system.txt"
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        logger.warning("Could not read reviewer_system.txt — using fallback")
        return (
            "You are a rigorous code reviewer. Evaluate the planner's "
            "proposal and return a structured JSON verdict with keys: "
            "kind (approve/revise/reject), summary, issues, confidence."
        )


def _build_user_prompt(request: ReviewRequest) -> str:
    """Build the user prompt for the reviewer from a review request."""
    parts = [
        f"## Checkpoint {request.checkpoint}",
        "",
        "### Proposal",
        request.proposal,
    ]
    if request.reasoning_summary:
        parts += ["", "### Reasoning Summary", request.reasoning_summary]
    parts += [
        "",
        "Return your review as a JSON object with keys: "
        '"kind" (approve/revise/reject), "summary" (string), '
        '"issues" (array of {severity, message, suggestion?}), '
        '"confidence" (0-1).',
    ]
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# LLM call
# ---------------------------------------------------------------------------


async def _call_reviewer_llm(user_prompt: str) -> dict | None:
    """Call the reviewer LLM and return the parsed JSON dict, or None.

    Follows the same pattern as :mod:`code_muse.plugins.auto_review.reviewer`:
    ModelFactory → pydantic-ai Agent (no tools) → parse JSON from text output.
    """
    try:
        from pydantic_ai import Agent as PydanticAgent

        from code_muse.agents._builder import load_muse_rules
        from code_muse.config import get_global_model_name
        from code_muse.model_factory import ModelFactory, make_model_settings
        from code_muse.model_utils import prepare_prompt_for_model

        # Resolve model name: config override → global default
        model_name = get_debate_reviewer_model() or get_global_model_name()
        if not model_name:
            logger.warning("No model available for debate reviewer")
            return None

        models_config = ModelFactory.load_config()
        if model_name not in models_config:
            logger.warning("Debate reviewer model '%s' not found in config", model_name)
            return None

        model = ModelFactory.get_model(model_name, models_config)
        if model is None:
            logger.warning("Could not create debate reviewer model instance")
            return None

        # Assemble instructions
        instructions = _load_reviewer_system_prompt()
        rules = load_muse_rules()
        if rules:
            instructions += f"\n\nProject rules:\n{rules}"

        prepared = prepare_prompt_for_model(
            model_name,
            instructions,
            user_prompt,
            prepend_system_to_user=False,
        )
        instructions = prepared.instructions
        user_prompt = prepared.user_prompt or user_prompt

        model_settings = make_model_settings(model_name)

        review_agent = PydanticAgent(
            model=model,
            instructions=instructions,
            output_type=str,
            retries=1,
            model_settings=model_settings,
        )

        result = await review_agent.run(user_prompt, message_history=[])
        text = (
            getattr(result, "output", None)
            or getattr(result, "data", None)
            or str(result)
        )

        return _parse_json_response(text)

    except Exception as exc:
        logger.error("Debate reviewer LLM call failed: %s", exc, exc_info=True)
        return None


# ---------------------------------------------------------------------------
# JSON parsing
# ---------------------------------------------------------------------------


def _parse_json_response(text: str) -> dict | None:
    """Extract a JSON object from the LLM's free-text response.

    Tries, in order:
    1. A fenced `````json ... ````` code block.
    2. The outermost ``{ … }`` in the text.
    3. The full text as JSON.

    Returns a dict on success, or None.
    """
    # 1) Fenced JSON block
    fence = re.search(r"```(?:json)?\s*(\{.*?})\s*```", text, re.DOTALL)
    if fence:
        try:
            return json.loads(fence.group(1))
        except json.JSONDecodeError, ValueError:
            pass

    # 2) Outermost braces
    start = text.find("{")
    end = text.rfind("}") + 1
    if start >= 0 and end > start:
        try:
            return json.loads(text[start:end])
        except json.JSONDecodeError, ValueError:
            pass

    # 3) Whole text
    try:
        return json.loads(text)
    except json.JSONDecodeError, ValueError:
        pass

    logger.warning("Reviewer returned unparseable response: %.200s", text)
    return None


def _json_to_verdict(data: dict) -> Verdict:
    """Convert a parsed JSON dict into a :class:`Verdict`.

    Tolerates missing/extra keys so that minor prompt drift doesn't crash.
    Falls back to ``revise`` when the kind is unrecognised.
    """
    raw_kind = str(data.get("kind", "revise")).lower().strip()
    try:
        kind = VerdictKind(raw_kind)
    except ValueError:
        logger.warning("Unknown verdict kind '%s' — treating as revise", raw_kind)
        kind = VerdictKind.REVISE

    summary = str(data.get("summary", "No summary provided"))[:500]

    issues: list[Issue] = []
    for item in data.get("issues", []):
        if isinstance(item, dict):
            issues.append(
                Issue(
                    severity=str(item.get("severity", "warning")),
                    message=str(item.get("message", "")),
                    suggestion=item.get("suggestion"),
                )
            )
        elif isinstance(item, str):
            issues.append(Issue(severity="warning", message=item))

    try:
        confidence = float(data.get("confidence", 0.5))
        confidence = max(0.0, min(1.0, confidence))
    except ValueError, TypeError:
        confidence = 0.5

    return Verdict(
        kind=kind,
        summary=summary,
        issues=issues,
        confidence=confidence,
    )


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
    """
    if not is_debate_enabled():
        logger.debug("Debate mode disabled — skipping review")
        return None

    user_prompt = _build_user_prompt(request)
    raw = await _call_reviewer_llm(user_prompt)

    if raw is None:
        # LLM call failed — treat as a lenient approve so the planner
        # isn't blocked by infrastructure issues.
        logger.warning("Reviewer LLM call failed — returning fallback approve")
        verdict = Verdict(
            kind=VerdictKind.APPROVE,
            summary="Reviewer unavailable — proceeding with caution.",
            confidence=0.0,
        )
    else:
        verdict = _json_to_verdict(raw)

    # NOTE: We do NOT call DebateState.record_review here — the caller
    # (the request_review tool function) handles all state recording
    # so that summary and latency_ms are captured.  Recording here would
    # cause double-counting.

    return ReviewResponse(
        verdict=verdict,
        review_count=DebateState.review_count(),
        remaining_budget=DebateState.remaining_budget(),
    )
