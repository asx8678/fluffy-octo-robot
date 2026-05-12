"""Callback registration for the MindPack plugin.

Registers:
- The 'register_tools' hook to expose the ask_mindpack tool to agents.
- The 'custom_command' + 'custom_command_help' hooks to expose the
  /ask_mindpack slash command for direct user invocation.
"""

import logging
from typing import Any

from code_muse.callbacks import register_callback
from code_muse.messaging import emit_info, emit_success, emit_warning

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Agent tool registration (existing)
# ---------------------------------------------------------------------------


def _register_mindpack_tools() -> list[dict[str, Any]]:
    """Callback for the 'register_tools' hook.

    Returns tool definitions that the core tool loader will merge
    into TOOL_REGISTRY.
    """
    from code_muse.plugins.mindpack.tools import register_ask_mindpack

    return [
        {"name": "ask_mindpack", "register_func": register_ask_mindpack},
    ]


# ---------------------------------------------------------------------------
# Slash-command help
# ---------------------------------------------------------------------------


def _custom_help() -> list[tuple[str, str]]:
    """Provide help entries for /help display."""
    return [
        (
            "ask_mindpack",
            "Run MindPack multi-expert advisory analysis on a problem",
        ),
        (
            "mindpack",
            "Manage MindPack profiles and expert panel (profiles bundle experts for different tasks)",
        ),
    ]


# ---------------------------------------------------------------------------
# Slash-command handler
# ---------------------------------------------------------------------------


async def _handle_custom_command(command: str, name: str) -> bool | None:
    """Handle the /ask_mindpack slash command.

    Extracts the user's problem description from the command text,
    spins up the MindPack expert panel, and displays the merged
    advisory output directly in the chat.

    Returns:
        True if the command was handled (advisory displayed).
        None if the command name doesn't match.
    """
    if name == "mindpack":
        from code_muse.plugins.mindpack.mindpack_menu import (
            interactive_mindpack_menu,
            interactive_profile_selector_menu,
        )

        # Profile selector first, then filtered expert menu
        while True:
            result = await interactive_profile_selector_menu()
            if result is None:
                break  # User exited profile selector
            if result is True:
                break  # Profile activated — exit to CLI
            # Otherwise it's a profile name — open expert list
            await interactive_mindpack_menu(profile_name=result)
        return True

    if name != "ask_mindpack":
        return None

    # Extract problem text after the command name
    parts = command.split(maxsplit=1)
    problem_text = parts[1].strip() if len(parts) > 1 else ""

    if not problem_text:
        emit_warning(
            "Usage: /ask_mindpack <your problem description>\n"
            "Example: /ask_mindpack How should I refactor the auth module "
            "to support multi-tenancy?"
        )
        return True

    from code_muse.plugins.mindpack.schemas import AskMindPackInput
    from code_muse.plugins.mindpack.tools import orchestrator

    emit_info("🧠 MindPack is consulting the expert panel…")

    active_profile = orchestrator.get_active_profile_name()
    if active_profile:
        emit_info(f"📋 Active profile: {active_profile}")

    request = AskMindPackInput(
        problem_statement=problem_text,
        current_goal="User requested advisory analysis via /ask_mindpack",
        desired_output="plan",
    )

    try:
        output = await orchestrator.consult(request)
    except Exception as exc:
        emit_warning(f"MindPack consultation failed: {exc}")
        return True

    # -- Display results ------------------------------------------------
    emit_success(f"🧠 MindPack Advisory Complete (confidence: {output.confidence:.2f})")

    emit_info(f"📋 Summary: {output.summary}")
    emit_info(f"🎯 Recommended Plan:\n{output.recommended_plan}")

    if output.ranked_options:
        emit_info("🏆 Ranked Options:")
        for opt in output.ranked_options:
            emit_info(
                f"  #{opt.rank} {opt.title} "
                f"[risk: {opt.risk}, confidence: {opt.confidence:.2f}]"
            )
            emit_info(f"    {opt.summary}")
            if opt.pros:
                emit_info(f"    Pros: {', '.join(opt.pros)}")
            if opt.cons:
                emit_info(f"    Cons: {', '.join(opt.cons)}")

    if output.risks:
        emit_warning("⚠️ Risks Identified:")
        for r in output.risks:
            emit_warning(f"  • {r}")

    if output.tests_to_run:
        emit_info("🧪 Suggested Tests:")
        for t in output.tests_to_run:
            emit_info(f"  • {t}")

    if output.files_to_inspect_or_change:
        emit_info("📁 Files to Inspect/Change:")
        for f in output.files_to_inspect_or_change:
            emit_info(f"  • {f}")

    if output.disagreements:
        emit_warning("⚡ Expert Disagreements:")
        for d in output.disagreements:
            emit_warning(f"  • {d}")

    emit_info(f"🤝 Expert Consensus: {output.expert_consensus}")

    return True  # Handled — no model invocation needed


# ---------------------------------------------------------------------------
# Register all callbacks
# ---------------------------------------------------------------------------

register_callback("register_tools", _register_mindpack_tools)
register_callback("custom_command_help", _custom_help)
register_callback("custom_command", _handle_custom_command)

logger.debug("MindPack plugin callbacks registered")
