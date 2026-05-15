"""Register Universal Critic plugin callbacks.

Registers:
    - agent_run_end hook for auto-review loop
    - /critic command for manual Universal Code Critic review
    - Help entries
"""

import logging

from code_muse.callbacks import register_callback
from code_muse.messaging import emit_info, emit_success, emit_warning

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Agent registration
# ---------------------------------------------------------------------------


def _register_agents():
    """Register the heavy and light coding agents."""
    from code_muse.agents.critic_heavy_agent import HeavyCodingAgent
    from code_muse.agents.critic_light_agent import LightCodingAgent

    return [
        {"name": "heavy-coding-agent", "class": HeavyCodingAgent},
        {"name": "light-coding-agent", "class": LightCodingAgent},
    ]


# ---------------------------------------------------------------------------
# Auto-review hook: delegate to orchestrator
# ---------------------------------------------------------------------------


async def _on_agent_run_end(
    agent_name: str,
    model_name: str,
    session_id: str | None = None,
    success: bool = True,
    error: str | None = None,
    response_text: str | None = None,
    metadata: dict | None = None,
) -> None:
    """Delegate to the orchestrator's auto-review after any agent run."""
    from code_muse.plugins.universal_critic.orchestrator import auto_review_after_run

    await auto_review_after_run(
        agent_name,
        model_name,
        session_id=session_id,
        success=success,
        error=error,
        response_text=response_text,
        metadata=metadata,
    )


# ---------------------------------------------------------------------------
# /critic custom command
# ---------------------------------------------------------------------------


async def _on_custom_command(command: str, name: str):
    """Handle /critic command."""
    if name != "critic":
        return None

    parts = command.split(maxsplit=2)
    subcommand = parts[1].strip() if len(parts) > 1 else ""

    # /critic — show workflow info
    if not subcommand:
        emit_info("🧐 Universal Code Critic — three-agent workflow:")
        emit_info("   • Light coding agent → edits ≤20 lines (typos, tweaks)")
        emit_info("   • Heavy coding agent → big files, features, >20 lines")
        emit_info("   • Code Critic → reviews all output automatically")
        emit_info("   Use /critic review <path> or /critic route <text>")
        return True

    # /critic review <path>
    if subcommand.startswith("review"):
        review_path = subcommand[6:].strip()
        if not review_path:
            emit_warning("Usage: /critic review <file_path>")
            return True

        from pathlib import Path

        from code_muse.plugins.universal_critic.orchestrator import (
            run_review,
        )

        p = Path(review_path)
        if not p.is_file():
            emit_warning(f"File not found: {review_path}")
            return True

        code = p.read_text(encoding="utf-8", errors="replace")
        emit_info(f"🔍 Universal Code Critic reviewing: {review_path}")
        result = await run_review(
            code_snippet=code, file_path=review_path, originating_agent="manual"
        )
        _emit_review_result(result, review_path)
        return True

    # /critic route <text>
    if subcommand.startswith("route"):
        route_text = subcommand[5:].strip()
        if not route_text:
            emit_warning("Usage: /critic route <task description>")
            return True

        from code_muse.plugins.universal_critic.models import TaskMetadata
        from code_muse.plugins.universal_critic.routing import (
            classify_complexity,
            estimate_task_size,
            is_new_file_task,
            route_task,
        )

        meta = TaskMetadata(
            original_prompt=route_text,
            estimated_lines=estimate_task_size(route_text),
            estimated_complexity=classify_complexity(route_text),
            has_new_file_creation=is_new_file_task(route_text),
        )
        destination = route_task(meta)
        emit_info(f"🗺️ Routing decision: {destination}")
        emit_info(f"   Estimated lines: {meta.estimated_lines}")
        emit_info(f"   Complexity: {meta.estimated_complexity}")
        emit_info(f"   New file task: {meta.has_new_file_creation}")
        return True

    emit_info("Usage: /critic [review <path> | route <text>]")
    return True


def _emit_review_result(result, file_path: str) -> None:
    """Emit the review result to the user."""
    if result.verdict == "approved":
        emit_success(f"✅ Universal Code Critic APPROVED {file_path}: {result.summary}")
    elif result.verdict == "rejected":
        emit_warning(f"❌ Universal Code Critic REJECTED {file_path}: {result.summary}")
        for issue in result.issues:
            emit_warning(f"   • {issue}")
        if result.suggestion:
            emit_info(f"   💡 Suggestion: {result.suggestion}")
    else:
        emit_info(f"⚠️ Universal Code Critic flagged {file_path}: {result.summary}")
        for issue in result.issues:
            emit_info(f"   • {issue}")


# ---------------------------------------------------------------------------
# Help and startup
# ---------------------------------------------------------------------------


def _on_custom_command_help():
    """Register help entries for the /critic command."""
    return [
        ("critic", "Show Universal Code Critic workflow info"),
        ("critic review <path>", "Review a file with Universal Code Critic"),
        ("critic route <text>", "See where a task would be routed"),
    ]


def _on_startup():
    """Log that Universal Critic plugin is loaded."""
    logger.debug(
        "Universal Code Critic plugin loaded — "
        "heavy/light coding agents + review loop ready."
    )


# ---------------------------------------------------------------------------
# Register all callbacks
# ---------------------------------------------------------------------------

register_callback("register_agents", _register_agents)
register_callback("agent_run_end", _on_agent_run_end)
register_callback("custom_command", _on_custom_command)
register_callback("custom_command_help", _on_custom_command_help)
register_callback("startup", _on_startup)

logger.debug("Universal Code Critic plugin callbacks registered")
