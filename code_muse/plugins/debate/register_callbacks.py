"""Callback registration for the Debate Mode plugin.

Registers:
    - ``request_review`` tool — called by the planner to submit a proposal
      for checkpoint review; the tool function itself invokes the reviewer
      LLM (via :func:`~code_muse.plugins.debate.reviewer.run_review`) and
      returns the structured verdict.
    - ``pre_tool_call`` hook — gates ``request_review`` calls when the
      budget is exhausted or a loop is detected (returns
      ``{"blocked": True}``).
    - ``load_prompt`` hook — injects the planner addendum into the
      agent's system prompt when debate mode is enabled.
    - ``agent_run_start`` / ``agent_run_end`` hooks — track the agent-run
      lifecycle so the debate state knows when reviews are in-context.
    - ``startup`` / ``shutdown`` hooks — session initialisation & cleanup.
    - ``/debate`` slash commands and help entries.
"""

import logging
import time
from pathlib import Path
from typing import Any

from code_muse.callbacks import register_callback
from code_muse.messaging import emit_info, emit_success, emit_warning
from code_muse.plugins.debate.config import is_debate_enabled
from code_muse.plugins.debate.reviewer import run_review
from code_muse.plugins.debate.schemas import ReviewRequest
from code_muse.plugins.debate.state import DebateState
from code_muse.plugins.debate.telemetry import get_session_stats, record_review_latency
from code_muse.plugins.debate.ui import render_verdict_summary

_PROMPTS_DIR = Path(__file__).parent / "prompts"

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Startup / Shutdown
# ---------------------------------------------------------------------------


def _on_startup() -> None:
    """Reset debate state on app boot."""
    DebateState.reset()
    logger.debug("Debate Mode plugin initialised")


def _on_shutdown() -> None:
    """Log final telemetry on graceful exit."""
    stats = get_session_stats()
    if stats["total_reviews"] > 0:
        logger.info("Debate session stats: %s", stats)


# ---------------------------------------------------------------------------
# Agent-run lifecycle hooks
# ---------------------------------------------------------------------------


async def _on_agent_run_start(
    agent_name: str,
    model_name: str,
    session_id: str | None = None,
) -> None:
    """Mark the debate session as active when an agent run starts."""
    if not is_debate_enabled():
        return
    DebateState.set_active(True, agent_name)
    logger.debug(
        "Debate: agent run started — agent=%s model=%s session=%s",
        agent_name,
        model_name,
        session_id,
    )


async def _on_agent_run_end(
    agent_name: str,
    model_name: str,
    session_id: str | None = None,
    success: bool = True,
    error: Exception | None = None,
    response_text: str | None = None,
    metadata: dict | None = None,
) -> None:
    """Mark the debate session as inactive when the agent run ends."""
    if not is_debate_enabled():
        return
    DebateState.set_active(False, agent_name)
    logger.debug("Debate: agent run ended — agent=%s success=%s", agent_name, success)


# ---------------------------------------------------------------------------
# Tool: request_review
# ---------------------------------------------------------------------------


def _register_debate_tools() -> list[dict[str, Any]]:
    """Return tool definitions for the debate mode plugin."""

    def register_request_review(agent):
        """Register the ``request_review`` tool on an agent."""

        @agent.tool
        async def request_review(
            context,
            proposal: str,
            reasoning_summary: str = "",
            checkpoint: int = 1,
        ) -> dict:
            """Submit the current proposal for checkpoint review.

            A second reviewer model evaluates the proposal and returns a
            structured verdict (approve / revise / reject).  The planner
            must call this at the end of each discrete proposal before
            proceeding.

            Args:
                proposal: The current proposal text to review.
                reasoning_summary: Brief summary of the reasoning leading \
                    to this proposal.
                checkpoint: Monotonically increasing checkpoint number.

            Returns:
                Dict with verdict, review count, and remaining budget.
            """
            if not is_debate_enabled():
                return {
                    "verdict": {
                        "kind": "approve",
                        "summary": "Debate mode disabled",
                    },
                    "review_count": 0,
                    "remaining_budget": 0,
                }

            # Build the review request and call the reviewer LLM.
            # run_review() records the review in DebateState internally.
            start = time.monotonic()
            request = ReviewRequest(
                proposal=proposal,
                reasoning_summary=reasoning_summary,
                checkpoint=checkpoint,
            )
            response = await run_review(request)
            elapsed_kind = response.verdict.kind if response else None

            if elapsed_kind is not None:
                record_review_latency(start, elapsed_kind)

            if response is not None:
                line = render_verdict_summary(
                    response.verdict.kind,
                    response.verdict.summary,
                    response.review_count,
                    response.remaining_budget,
                )
                emit_info(line)
                return response.model_dump()

            # Reviewer unreachable — return fallback so planner isn't stuck
            return {
                "verdict": {
                    "kind": "approve",
                    "summary": "Review unavailable — proceeding",
                },
                "review_count": DebateState.review_count(),
                "remaining_budget": DebateState.remaining_budget(),
            }

    return [
        {"name": "request_review", "register_func": register_request_review},
    ]


# ---------------------------------------------------------------------------
# pre_tool_call hook — budget enforcement & loop detection
# ---------------------------------------------------------------------------


async def _on_pre_tool_call(
    tool_name: str, tool_args: dict, context: Any = None
) -> dict | None:
    """Gate ``request_review`` calls when limits are hit.

    Returns ``{"blocked": True}`` to prevent the call; returns ``None``
    to allow it.

    Only gates the ``request_review`` tool — all other tools pass through.
    """
    if tool_name != "request_review":
        return None

    if not is_debate_enabled():
        return None  # let the tool handle the disabled case

    if DebateState.is_budget_exhausted():
        emit_warning("🚫 Debate budget exhausted — no further reviews this session")
        return {"blocked": True}

    if DebateState.is_loop_detected():
        emit_warning(
            "🚫 Debate loop detected — too many consecutive revisions. "
            "Revise your approach before requesting another review."
        )
        return {"blocked": True}

    return None


# ---------------------------------------------------------------------------
# load_prompt hook — inject planner addendum into system prompt
# ---------------------------------------------------------------------------


def _on_load_prompt() -> str | None:
    """Inject the planner addendum into the agent's system prompt.

    When debate mode is enabled, the planner must be told it operates
    under checkpoint review rules — call ``request_review`` after each
    proposal, wait for verdict, revise if told to.

    Returns the addendum text, or ``None`` when debate mode is disabled.
    """
    if not is_debate_enabled():
        return None

    path = _PROMPTS_DIR / "planner_addendum.txt"
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        logger.warning("Could not read planner_addendum.txt")
        return None


# ---------------------------------------------------------------------------
# Slash commands
# ---------------------------------------------------------------------------


def _on_custom_command(command: str, name: str) -> bool | None:
    """Handle ``/debate`` slash commands."""
    if name != "debate":
        return None

    parts = command.split(maxsplit=1)
    sub = parts[1].strip().lower() if len(parts) > 1 else ""

    if sub == "stats":
        stats = get_session_stats()
        emit_info(f"📊 Debate stats: {stats}")
        return True

    if sub == "reset":
        DebateState.reset()
        emit_success("🔄 Debate state reset")
        return True

    emit_info("Usage: /debate stats | /debate reset")
    return True


def _on_custom_command_help() -> list[tuple[str, str]]:
    return [
        ("debate stats", "Show debate-mode session statistics"),
        ("debate reset", "Reset debate-mode session state"),
    ]


# ---------------------------------------------------------------------------
# Register all callbacks
# ---------------------------------------------------------------------------

register_callback("startup", _on_startup)
register_callback("shutdown", _on_shutdown)
register_callback("agent_run_start", _on_agent_run_start)
register_callback("agent_run_end", _on_agent_run_end)
register_callback("register_tools", _register_debate_tools)
register_callback("pre_tool_call", _on_pre_tool_call)
register_callback("load_prompt", _on_load_prompt)
register_callback("custom_command", _on_custom_command)
register_callback("custom_command_help", _on_custom_command_help)

logger.debug("Debate Mode plugin callbacks registered")
