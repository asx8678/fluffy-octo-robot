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
    - ``stream_event`` hook — renders inline review indicators during
      planner streaming (before tool execution).
    - ``/debate`` slash commands: ``on``, ``off``, ``toggle``, ``status``,
      ``stats``, ``metrics``, ``history``, ``reset``.
"""

import logging
import time
from pathlib import Path
from typing import Any

from code_muse.callbacks import register_callback
from code_muse.messaging import emit_info, emit_success, emit_warning
from code_muse.plugins.debate.config import (
    get_debate_max_loops,
    get_debate_max_reviews,
    is_debate_enabled,
    set_debate_enabled,
)
from code_muse.plugins.debate.reviewer import run_review
from code_muse.plugins.debate.schemas import ReviewRequest
from code_muse.plugins.debate.state import DebateState
from code_muse.plugins.debate.telemetry import (
    get_latency_stats,
    get_session_stats,
    get_success_rate,
    get_verdict_breakdown,
    record_review_latency,
    reset_telemetry,
)
from code_muse.plugins.debate.ui import (
    render_progress_bar,
    render_review_history,
    render_status_panel,
    show_reviewing,
    show_verdict,
)

_PROMPTS_DIR = Path(__file__).parent / "prompts"

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Startup / Shutdown
# ---------------------------------------------------------------------------


def _on_startup() -> None:
    """Reset debate state and telemetry on app boot."""
    DebateState.reset()
    reset_telemetry()
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

            # Show progress indicator while review is running
            emit_info(show_reviewing(checkpoint, proposal))

            # Build the review request and call the reviewer LLM.
            start = time.monotonic()
            request = ReviewRequest(
                proposal=proposal,
                reasoning_summary=reasoning_summary,
                checkpoint=checkpoint,
            )
            response = await run_review(request)
            elapsed_ms = (time.monotonic() - start) * 1000

            if response is not None:
                verdict = response.verdict
                record_review_latency(start, verdict.kind)

                # Record in debate state with history
                DebateState.record_review(
                    checkpoint=checkpoint,
                    verdict_kind=verdict.kind,
                    summary=verdict.summary,
                    latency_ms=elapsed_ms,
                )

                # Show rich verdict display
                emit_info(
                    show_verdict(
                        kind=verdict.kind,
                        summary=verdict.summary,
                        issues=[iss.model_dump() for iss in verdict.issues],
                        confidence=verdict.confidence,
                        review_count=response.review_count,
                        remaining_budget=response.remaining_budget,
                    )
                )
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
# Slash commands: /debate on|off|toggle|status|stats|metrics|history|reset
# ---------------------------------------------------------------------------


def _on_custom_command(command: str, name: str) -> bool | None:
    """Handle ``/debate`` slash commands.

    Subcommands:
        on      — Enable debate mode
        off     — Disable debate mode
        toggle  — Toggle debate mode on/off
        status  — Show full status panel
        stats   — Show session statistics summary
        metrics — Show detailed latency and verdict breakdown
        history — Show review history table
        reset   — Reset all debate state and telemetry
    """
    if name != "debate":
        return None

    parts = command.split(maxsplit=1)
    sub = parts[1].strip().lower() if len(parts) > 1 else "status"

    # --- Toggle commands ---
    if sub == "on":
        set_debate_enabled(True)
        emit_success("⚖️ Debate mode enabled")
        return True

    if sub == "off":
        set_debate_enabled(False)
        emit_warning("⚖️ Debate mode disabled")
        return True

    if sub == "toggle":
        current = is_debate_enabled()
        set_debate_enabled(not current)
        new_state = "enabled" if not current else "disabled"
        emoji = "✅" if not current else "⚠️"
        emit_info(f"{emoji} Debate mode {new_state}")
        return True

    # --- Status command ---
    if sub == "status":
        stats = get_session_stats()
        panel = render_status_panel(
            enabled=is_debate_enabled(),
            active=DebateState.is_active(),
            agent_name=DebateState.agent_name(),
            review_count=DebateState.review_count(),
            remaining_budget=DebateState.remaining_budget(),
            max_reviews=get_debate_max_reviews(),
            consecutive_revisions=DebateState.consecutive_revisions(),
            max_loops=get_debate_max_loops(),
            avg_latency_ms=stats.get("avg_latency_ms", 0.0),
        )
        emit_info(panel)
        return True

    # --- Stats command ---
    if sub == "stats":
        stats = get_session_stats()
        success = get_success_rate()
        bar = render_progress_bar(stats["total_reviews"], get_debate_max_reviews())
        lines = [
            "📊 Debate Session Stats:",
            f"   Reviews: {stats['total_reviews']}",
            f"   Budget:  {bar}",
            f"   Success: {success:.1%}",
            f"   Avg latency: {stats['avg_latency_ms']:.0f}ms",
        ]
        emit_info("\n".join(lines))
        return True

    # --- Metrics command (detailed) ---
    if sub == "metrics":
        stats = get_session_stats()
        latency = get_latency_stats()
        breakdown = get_verdict_breakdown()
        success = get_success_rate()
        lines = [
            "📈 Debate Metrics:",
            f"   Total reviews:   {stats['total_reviews']}",
            f"   Success rate:    {success:.1%}",
            "",
            "   Verdict breakdown:",
            f"     ✅ Approve: {breakdown.get('approve', 0)}",
            f"     🔄 Revise:  {breakdown.get('revise', 0)}",
            f"     ❌ Reject:  {breakdown.get('reject', 0)}",
            "",
            "   Latency:",
            f"     Avg:  {latency['avg_ms']:.0f}ms",
            f"     Min:  {latency['min_ms']:.0f}ms",
            f"     Max:  {latency['max_ms']:.0f}ms",
            f"     Total: {latency['total_ms']:.0f}ms",
            "",
            f"   Reviews/min: {stats.get('reviews_per_minute', 0):.1f}",
        ]
        emit_info("\n".join(lines))
        return True

    # --- History command ---
    if sub == "history":
        history = DebateState.review_history()
        emit_info(render_review_history(history))
        return True

    # --- Reset command ---
    if sub == "reset":
        DebateState.reset()
        reset_telemetry()
        emit_success("🔄 Debate state and telemetry reset")
        return True

    # --- Unknown subcommand ---
    emit_info("Usage: /debate on|off|toggle|status|stats|metrics|history|reset")
    return True


def _on_custom_command_help() -> list[tuple[str, str]]:
    """Return help entries for the ``/debate`` command family."""
    return [
        ("debate on", "Enable debate mode"),
        ("debate off", "Disable debate mode"),
        ("debate toggle", "Toggle debate mode on/off"),
        ("debate status", "Show full debate status panel"),
        ("debate stats", "Show session statistics summary"),
        ("debate metrics", "Show detailed latency & verdict breakdown"),
        ("debate history", "Show review history table"),
        ("debate reset", "Reset all debate state and telemetry"),
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


# ---------------------------------------------------------------------------
# stream_event hook — inline verdict rendering during planner output
# ---------------------------------------------------------------------------


# Track which tool-call part indices are request_review so we can
# render a compact indicator at part_end time.
_pending_review_indices: set[int] = set()


def _on_stream_event(
    event_type: str, event_data: Any, agent_session_id: str | None = None
) -> None:
    """Render inline review indicators during planner streaming.

    When the planner starts emitting a ``request_review`` tool call
    (``part_start``), this hook fires a compact indicator *before* the
    tool executes — giving the user immediate feedback that a review
    is pending.

    The actual verdict is rendered by the tool function via
    :func:`show_verdict`, so this hook only shows a brief inline
    cue at the point the planner produces the call.
    """
    if not is_debate_enabled():
        return

    if event_type == "part_start":
        part = event_data.get("part")
        part_type = event_data.get("part_type", "")
        if part_type == "ToolCallPart" and part is not None:
            tool_name = getattr(part, "tool_name", None) or ""
            if tool_name == "request_review":
                idx = event_data.get("index", -1)
                _pending_review_indices.add(idx)
                emit_info("⚖️  Review requested — awaiting verdict…")

    elif event_type == "part_end":
        idx = event_data.get("index", -1)
        if idx in _pending_review_indices:
            _pending_review_indices.discard(idx)


register_callback("stream_event", _on_stream_event)

logger.debug("Debate Mode plugin callbacks registered")
