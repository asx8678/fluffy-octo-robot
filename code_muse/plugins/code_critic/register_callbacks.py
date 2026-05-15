"""Register Universal Code Critic callbacks.

Registers:
    - code-critic agent via register_agents hook
    - agent_run_end hook for auto-review after agent runs
    - /critic command for manual review
"""

import logging

from code_muse.callbacks import register_callback
from code_muse.messaging import emit_info, emit_success, emit_warning

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Agent registration
# ---------------------------------------------------------------------------


def _register_agents():
    """Register the code-critic agent."""
    from code_muse.plugins.code_critic.critic_agent import CodeCriticAgent

    return [{"name": "code-critic", "class": CodeCriticAgent}]


# ---------------------------------------------------------------------------
# Auto-review hook: runs after any agent finishes
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
    """Review code changes after an agent run completes.

    Only reviews for agents that produce code (not the critic itself).
    Only reviews if the run was successful.
    """

    # Don't review the critic's own runs
    if agent_name == "code-critic":
        return

    if not success:
        return

    # Check if there are recent file changes worth reviewing
    # We do this by looking at what was produced
    # For now, this is a lightweight check — pass key changes to the critic
    if metadata and "review_files" in metadata:
        from code_muse.plugins.code_critic.reviewer import review_file

        files_to_review = metadata["review_files"]
        if isinstance(files_to_review, str):
            files_to_review = [files_to_review]

        for file_path in files_to_review:
            emit_info(f"🔍 Universal Code Critic reviewing: {file_path}")
            verdict = await review_file(file_path, agent_name=agent_name)
            _emit_verdict(verdict, file_path, agent_name)


def _emit_verdict(verdict: dict, file_path: str, agent_name: str) -> None:
    """Emit the review verdict to the user."""
    v = verdict.get("verdict", "flagged")
    summary = verdict.get("summary", "No summary")
    issues = verdict.get("issues", [])
    suggestion = verdict.get("suggestion")

    if v == "approved":
        emit_success(f"✅ Universal Code Critic APPROVED {file_path}: {summary}")
    elif v == "rejected":
        emit_warning(f"❌ Universal Code Critic REJECTED {file_path}: {summary}")
        for issue in issues:
            emit_warning(f"   • {issue}")
        if suggestion:
            emit_info(f"   💡 Suggestion: {suggestion}")
    else:
        emit_info(f"⚠️  Universal Code Critic flagged {file_path}: {summary}")
        for issue in issues:
            emit_info(f"   • {issue}")


# ---------------------------------------------------------------------------
# /critic custom command
# ---------------------------------------------------------------------------


async def _on_custom_command(command: str, name: str):
    """Handle /critic command."""
    if name != "critic":
        return None

    from code_muse.agents.agent_manager import set_current_agent

    parts = command.split(maxsplit=1)
    subcommand = parts[1].strip() if len(parts) > 1 else ""

    if not subcommand:
        # Just switch to the critic agent
        success = set_current_agent("code-critic")
        if success:
            emit_success("Switched to Universal Code Critic 🧐 — ready to review!")
        else:
            emit_info("Could not find Universal Code Critic agent.")
        return True

    # /critic review <path>
    if subcommand.startswith("review"):
        review_path = subcommand[6:].strip()
        if not review_path:
            emit_warning("Usage: /critic review <file_path>")
            return True

        from code_muse.plugins.code_critic.reviewer import review_file

        emit_info(f"🔍 Universal Code Critic reviewing: {review_path}")
        verdict = await review_file(review_path, agent_name="manual")
        _emit_verdict(verdict, review_path, "manual")
        return True

    emit_info("Usage: /critic [review <path>]")
    return True


def _on_custom_command_help():
    """Register help entries for the /critic command."""
    return [
        ("critic", "Switch to Universal Code Critic agent for code review"),
        ("critic review <path>", "Review a specific file with Universal Code Critic"),
    ]


# ---------------------------------------------------------------------------
# Startup message
# ---------------------------------------------------------------------------


def _on_startup():
    """Log that Universal Code Critic is loaded."""
    logger.debug("Universal Code Critic plugin loaded — ready to review code.")


# ---------------------------------------------------------------------------
# Register all callbacks
# ---------------------------------------------------------------------------

register_callback("register_agents", _register_agents)
register_callback("agent_run_end", _on_agent_run_end)
register_callback("custom_command", _on_custom_command)
register_callback("custom_command_help", _on_custom_command_help)
register_callback("startup", _on_startup)

logger.debug("Universal Code Critic plugin callbacks registered")
