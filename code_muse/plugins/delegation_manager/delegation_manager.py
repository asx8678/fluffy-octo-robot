"""Delegation Manager — creates isolated sub-agent runs with caching.

The DelegationManager is the engine behind the Supervisor agent.  It:

1. Dynamically builds delegation tool functions (one per available agent).
2. Caches sub-agent results to avoid re-running identical tasks.
3. Tracks active tasks and provides graceful error handling.

Sub-agents are **fully isolated** — they receive only the task + context
that the supervisor explicitly provides.  No conversation history is passed.
"""

import asyncio
import hashlib
import logging
import threading
from collections.abc import Callable
from typing import Any

from pydantic_ai import Agent, RunContext, UsageLimits

from code_muse.config import get_message_limit
from code_muse.tools.subagent_context import subagent_context

logger = logging.getLogger(__name__)


class DelegationManager:
    """Manages creation, caching, and execution of delegation tools."""

    def __init__(self) -> None:
        self._result_cache: dict[str, str] = {}
        self._active_tasks: dict[str, asyncio.Task] = {}
        self._lock = threading.Lock()

    def create_delegation_function(
        self, agent_name: str, agent_config: Any
    ) -> Callable:
        """Create a delegation tool function for a sub-agent.

        The returned function is suitable for registration as a pydantic-ai
        tool via ``agent.tool(delegate_func)``.
        """

        async def delegate_to(
            ctx: RunContext, task_description: str, context: str = ""
        ) -> str:
            """Delegate a task to a specialized sub-agent.

            Sub-agents are ISOLATED — they receive ONLY this task + context.
            They do NOT have access to your conversation history or prior tool
            results.

            Args:
                task_description: Clear, detailed task for the sub-agent.
                context: ALL context the sub-agent needs (file paths, code
                    snippets, error messages, etc.) since they're isolated from
                    conversation.
            """
            cache_key = self._make_cache_key(agent_name, task_description, context)

            # Check cache first
            cached = self._get_cached(cache_key)
            if cached is not None:
                return cached

            # Execute sub-agent
            result = await self._run_subagent(
                agent_name, task_description, context, cache_key
            )
            return result

        # Fix up metadata so pydantic-ai schema generation is clean
        safe_name = agent_name.replace("-", "_")
        delegate_to.__name__ = f"delegate_to_{safe_name}"
        delegate_to.__doc__ = (
            f"Delegate a task to the {agent_name} sub-agent. "
            f"The sub-agent is isolated — it only receives the task + context you provide.\n\n"
            f"Args:\n"
            f"    task_description: The task to perform\n"
            f"    context: All relevant context (file paths, code, errors, etc.)"
        )
        return delegate_to

    # ------------------------------------------------------------------
    # Cache helpers
    # ------------------------------------------------------------------

    def _make_cache_key(self, agent_name: str, task: str, context: str) -> str:
        raw = f"{agent_name}:{task}:{context}"
        return hashlib.sha256(raw.encode()).hexdigest()[:32]

    def _get_cached(self, cache_key: str) -> str | None:
        with self._lock:
            return self._result_cache.get(cache_key)

    def _cache_result(self, cache_key: str, result: str) -> None:
        with self._lock:
            self._result_cache[cache_key] = result

    # ------------------------------------------------------------------
    # Sub-agent execution
    # ------------------------------------------------------------------

    async def _run_subagent(
        self, agent_name: str, task_desc: str, context: str, cache_key: str
    ) -> str:
        """Invoke the sub-agent using Muse's agent construction pattern.

        Mimics ``code_muse/tools/agent_tools.py::invoke_agent`` but with
        **full isolation**: no message history, no prior context, no
        session persistence.
        """
        from code_muse.agents.agent_manager import load_agent
        from code_muse.model_factory import ModelFactory, make_model_settings
        from code_muse.tools import register_tools_for_agent

        try:
            # Load sub-agent config
            sub_agent_config = load_agent(agent_name)

            # Build prompt with full context (no history = isolated)
            instructions = sub_agent_config.get_full_system_prompt()

            # Load muse rules if available
            try:
                from code_muse.agents._builder import load_muse_rules

                rules = load_muse_rules()
                if rules:
                    instructions += f"\n\n{rules}"
            except ImportError:
                pass

            # Load prompt additions from plugins
            try:
                from code_muse import callbacks

                prompt_additions = callbacks.on_load_prompt()
                if prompt_additions:
                    instructions += "\n" + "\n".join(prompt_additions)
            except Exception:
                pass

            # Create temporary pydantic-ai agent
            model_name = sub_agent_config.get_model_name()
            models_config = ModelFactory.load_config()
            model = ModelFactory.get_model(model_name, models_config)

            model_settings = make_model_settings(model_name)

            temp_agent = Agent(
                model=model,
                instructions=instructions,
                output_type=str,
                retries=2,
                model_settings=model_settings,
            )

            # Register tools for the sub-agent
            agent_tools = sub_agent_config.get_available_tools()
            register_tools_for_agent(temp_agent, agent_tools, model_name=model_name)

            # Build the combined prompt
            prompt = f"## Task\n\n{task_desc}\n\n## Context\n\n{context}"

            # Run the sub-agent with isolation
            with subagent_context(agent_name):
                result = await temp_agent.run(
                    prompt,
                    message_history=[],  # ISOLATED — no history!
                    usage_limits=UsageLimits(request_limit=get_message_limit()),
                )

            response = result.output if result.output else ""
            self._cache_result(cache_key, response)
            return response

        except Exception as e:
            logger.warning(f"Sub-agent {agent_name} failed: {e}")
            error_msg = f"Error in {agent_name} sub-agent: {type(e).__name__}: {e}"
            self._cache_result(cache_key, error_msg)
            return error_msg
