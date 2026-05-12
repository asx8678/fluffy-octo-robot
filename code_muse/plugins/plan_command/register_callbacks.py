"""Plan Command Plugin — /plan slash command.

Invokes the planning-agent to break down a coding task into
clear, actionable steps and displays the plan to the user.
"""

import logging
from contextlib import AsyncExitStack
from dataclasses import dataclass
from functools import partial

from code_muse.callbacks import on_agent_run_context, register_callback
from code_muse.messaging import emit_info, emit_success, emit_warning

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Lightweight standalone agent invocation (mirrors invoke_agent tool logic)
# ---------------------------------------------------------------------------


@dataclass
class _AgentResult:
    """Simple container for an invoked agent's response."""

    response_text: str | None = None
    error: str | None = None


async def _invoke_agent(agent_name: str, prompt: str) -> _AgentResult:
    """Invoke a named agent with a prompt and return its text response.

    This is a lightweight standalone wrapper that mirrors the core
    ``invoke_agent`` tool logic but doesn't require a Pydantic-AI
    ``RunContext`` — making it callable from plugin callbacks.
    """
    from pydantic_ai import Agent, UsageLimits

    from code_muse.agents._compaction import make_history_processor
    from code_muse.agents.agent_manager import load_agent
    from code_muse.agents.subagent_stream_handler import subagent_stream_handler
    from code_muse.config import get_message_limit
    from code_muse.model_factory import ModelFactory, make_model_settings
    from code_muse.model_utils import prepare_prompt_for_model
    from code_muse.tools import register_tools_for_agent
    from code_muse.tools.common import generate_group_id
    from code_muse.tools.subagent_context import subagent_context

    group_id = generate_group_id("invoke_agent", agent_name)

    try:
        agent_config = load_agent(agent_name)

        model_name = agent_config.get_model_name()
        models_config = ModelFactory.load_config()

        if model_name not in models_config:
            return _AgentResult(
                error=f"Model '{model_name}' not found in configuration"
            )

        model = ModelFactory.get_model(model_name, models_config)

        instructions = agent_config.get_full_system_prompt()

        # Add AGENTS.md content
        from code_muse.agents._builder import load_muse_rules

        agent_rules = load_muse_rules()
        if agent_rules:
            instructions += f"\n\n{agent_rules}"

        # Apply plugin prompt additions
        from code_muse import callbacks as cb

        prompt_additions = cb.on_load_prompt()
        if prompt_additions:
            instructions += "\n" + "\n".join(prompt_additions)

        # Prepare prompt for model (handles claude-code models etc.)
        prepared = prepare_prompt_for_model(
            model_name,
            instructions,
            prompt,
            prepend_system_to_user=True,
        )
        instructions = prepared.instructions
        prompt = prepared.user_prompt

        model_settings = make_model_settings(model_name)

        temp_agent = Agent(
            model=model,
            instructions=instructions,
            output_type=str,
            retries=3,
            toolsets=[],
            history_processors=[make_history_processor(agent_config)],
            model_settings=model_settings,
        )

        # Register the tools the agent needs
        agent_tools = agent_config.get_available_tools()
        register_tools_for_agent(temp_agent, agent_tools, model_name=model_name)

        # Use subagent_stream_handler for clean output
        stream_handler = partial(
            subagent_stream_handler, session_id=f"{agent_name}-plan-session"
        )

        with subagent_context(agent_name):
            run_ctxs = on_agent_run_context(agent_config, temp_agent, group_id)
            async with AsyncExitStack() as stack:
                for cm in run_ctxs:
                    await stack.enter_async_context(cm)
                result = await temp_agent.run(
                    prompt,
                    message_history=[],
                    usage_limits=UsageLimits(request_limit=get_message_limit()),
                    event_stream_handler=stream_handler,
                )

        return _AgentResult(response_text=result.output)

    except Exception as exc:
        logger.exception("invoke_agent failed for %s", agent_name)
        return _AgentResult(error=str(exc))


# ---------------------------------------------------------------------------
# Slash-command help
# ---------------------------------------------------------------------------


def _custom_help() -> list[tuple[str, str]]:
    """Provide help entry for /help display."""
    return [
        ("plan", "Invoke the Planning Agent to create an execution roadmap"),
    ]


# ---------------------------------------------------------------------------
# Slash-command handler
# ---------------------------------------------------------------------------


async def _handle_custom_command(command: str, name: str) -> bool | None:
    """Handle the /plan slash command.

    Usage:
        /plan <description of what to plan>

    Invokes the planning-agent with the user's request and displays
    the resulting plan.

    Returns:
        True if handled.
        None if the command name doesn't match.
    """
    if name != "plan":
        return None

    # Extract the planning request (everything after "/plan")
    parts = command.split(maxsplit=1)
    plan_request = parts[1].strip() if len(parts) > 1 else ""

    if not plan_request:
        emit_warning(
            "Usage: /plan <description of what to plan>\n"
            "Example: /plan Add user authentication with OAuth2"
        )
        return True

    emit_info("📋 Planning Agent is creating your roadmap…")

    result = await _invoke_agent(
        agent_name="planning-agent",
        prompt=(
            f"Create a detailed execution plan for the following task:\n\n"
            f"{plan_request}\n\n"
            f"Include: project structure analysis, dependencies, "
            f"execution steps, and validation strategy."
        ),
    )

    # Display the plan
    if result.response_text:
        emit_success("📋 Planning Agent — Execution Roadmap")
        emit_info(result.response_text)
    elif result.error:
        emit_warning(f"Planning Agent error: {result.error}")
    else:
        emit_warning("Planning Agent returned no output.")

    return True  # Handled — no additional model invocation needed


# ---------------------------------------------------------------------------
# Register callbacks
# ---------------------------------------------------------------------------

register_callback("custom_command_help", _custom_help)
register_callback("custom_command", _handle_custom_command)

logger.debug("Plan Command plugin callbacks registered")
