"""Expert agent factory — creates read-only sub-agents from ExpertDescriptors.

Follows the same sub-agent construction pattern as
``code_muse.tools.agent_tools.register_invoke_agent`` but with two key
constraints:

1. **Read-only tool set** — experts can inspect code but never mutate it.
2. **Structured output** — experts return ``ExpertReport`` models, not free
   text, so the judge merger receives machine-parseable data.

The factory is deliberately stateless: it builds an agent per call and
tears it down afterwards.  No session history is persisted to disk because
expert consultations are ephemeral — they exist only for the duration of a
single ``MindPackOrchestrator.consult()`` call.
"""

import asyncio
import logging
import uuid
from contextlib import AsyncExitStack
from functools import partial
from typing import Any, get_args

from pydantic_ai import Agent as PydanticAgent
from pydantic_ai import UsageLimits

from code_muse.plugins.mindpack.schemas import (
    AskMindPackInput,
    ExpertDescriptor,
    ExpertSpawnMode,
    MindPackExpertPoolConfig,
)
from code_muse.plugins.mindpack.schemas import MindPackExpertReport as ExpertReport
from code_muse.tools.subagent_context import subagent_context

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# INI config helpers
# ---------------------------------------------------------------------------


def _get_config_str(key: str, default: str) -> str:
    from code_muse.config import get_value

    return get_value(key) or default


def _get_config_int(key: str, default: int) -> int:
    from code_muse.config import get_value

    val = get_value(key)
    if val is None:
        return default
    try:
        return int(val)
    except (ValueError, TypeError):
        logger.warning(
            "Invalid integer config '%s=%s'; using default %s", key, val, default
        )
        return default


def _get_config_bool(key: str, default: bool) -> bool:
    from code_muse.config import get_value

    val = get_value(key)
    if val is None:
        return default
    return str(val).lower() in ("1", "true", "yes", "on")


def load_pool_config_from_ini(
    overrides: MindPackExpertPoolConfig | None = None,
) -> MindPackExpertPoolConfig:
    """Build a ``MindPackExpertPoolConfig`` from INI settings.

    Reads ``packmind_expert_spawn_mode``, ``packmind_expert_count``,
    ``packmind_min_experts``, ``packmind_max_experts``, and
    ``packmind_model_strategy`` from the Muse INI config.

    Any caller-supplied ``overrides`` take precedence over INI values.
    """
    spawn_mode_raw = _get_config_str("packmind_expert_spawn_mode", "fixed")
    valid_modes = set(get_args(ExpertSpawnMode))
    if spawn_mode_raw not in valid_modes:
        logger.warning(
            "Invalid packmind_expert_spawn_mode '%s'; falling back to 'fixed'",
            spawn_mode_raw,
        )
        spawn_mode_raw = "fixed"

    config = MindPackExpertPoolConfig(
        spawn_mode=spawn_mode_raw,  # type: ignore[arg-type]
        default_expert_count=_get_config_int("packmind_expert_count", 5),
        min_experts=_get_config_int("packmind_min_experts", 3),
        max_experts=_get_config_int("packmind_max_experts", 7),
        model_strategy=_get_config_str("packmind_model_strategy", "same_model"),  # type: ignore[arg-type]
    )

    if overrides is not None:
        # Apply caller overrides field-by-field
        for field_name in MindPackExpertPoolConfig.model_fields:
            override_val = getattr(overrides, field_name, None)
            if override_val is not None:
                setattr(config, field_name, override_val)

    return config


# ---------------------------------------------------------------------------
# Read-only tool allow-list
# ---------------------------------------------------------------------------

READ_ONLY_TOOLS: list[str] = [
    "list_files",
    "read_file",
    "grep",
    "load_image_for_analysis",
    "list_or_search_skills",
]
"""Tools that an expert agent may use.  All write-capable tools (create_file,
replace_in_file, delete_snippet, delete_file, agent_run_shell_command,
ask_user_question, invoke_agent, list_agents, browser_*, activate_skill,
universal_constructor) are deliberately excluded."""

# ---------------------------------------------------------------------------
# Expert system prompt template
# ---------------------------------------------------------------------------

_EXPERT_SYSTEM_PROMPT_TEMPLATE = """\
You are {expert_name}, a specialist in {speciality}.

{system_prompt_fragment}

## CRITICAL CONSTRAINTS

You are operating in **read-only advisory mode**. You must NEVER:

- Create, modify, or delete any files
- Run shell commands
- Invoke other agents or sub-agents
- Ask the user questions
- Navigate websites or use browser tools

You MAY:
- List and read files
- Search code with grep
- Load images for analysis

Your task is to analyse the problem, explore the relevant code, and produce
a structured report with your findings, recommendations, identified risks,
and confidence level.

## OUTPUT FORMAT

You MUST produce your response as a structured report containing:
- **summary**: Your detailed analysis of the problem
- **findings**: Key findings and observations
- **proposed_plan**: A list of specific, actionable recommendations
- **risks**: A list of risks, edge cases, or failure modes you identified
- **files_to_inspect**: Files you recommend the executor inspect or change
- **tests_to_run**: Tests you recommend running
- **confidence**: Your confidence in your analysis (0.0 to 1.0)
- **assumptions**: Any assumptions you made
"""

# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------


def build_expert_prompt(
    expert: ExpertDescriptor,
    request: AskMindPackInput,
) -> str:
    """Compose the user-facing prompt for an expert consultation.

    The prompt carries the full problem context so the expert can work
    autonomously with only read-only tools.
    """
    parts: list[str] = []

    parts.append(f"## Problem Statement\n{request.problem_statement}")

    parts.append(f"## Current Goal\n{request.current_goal}")

    if request.current_plan:
        parts.append(f"## Current Plan\n{request.current_plan}")

    if request.what_has_been_tried:
        parts.append(
            "## What Has Been Tried\n"
            + "\n".join(f"- {item}" for item in request.what_has_been_tried)
        )

    if request.relevant_files:
        parts.append(
            "## Relevant Files\n" + "\n".join(f"- {f}" for f in request.relevant_files)
        )

    if request.observed_errors:
        parts.append(
            "## Observed Errors\n"
            + "\n".join(f"- {e}" for e in request.observed_errors)
        )

    if request.uncertainty:
        parts.append(f"## Uncertainty\n{request.uncertainty}")

    parts.append(f"## Desired Output Type\n{request.desired_output}")

    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# ExpertAgentFactory
# ---------------------------------------------------------------------------


class ExpertAgentFactory:
    """Creates and runs read-only expert sub-agents.

    Usage::

        factory = ExpertAgentFactory()
        report = await factory.invoke_expert(descriptor, request, session_id)
    """

    def __init__(self) -> None:
        self._concurrency_limit = _get_config_int("packmind_concurrency_limit", 8)
        self._semaphore = asyncio.Semaphore(self._concurrency_limit)
        logger.debug(
            "ExpertAgentFactory: concurrency limit set to %d",
            self._concurrency_limit,
        )

    def create_expert_agent(
        self,
        expert: ExpertDescriptor,
        *,
        session_id: str,
        message_group: str | None = None,
        model_override: str | None = None,
    ) -> PydanticAgent:
        """Build a pydantic-ai agent for the given expert descriptor.

        The agent is configured with:
        - The expert's system prompt (identity + fragment + constraints)
        - Read-only tools only
        - ``ExpertReport`` as the structured output type

        This is a **temporary agent** — it is not registered in the agent
        manager and does not persist across calls.
        """
        from code_muse.agents._builder import load_muse_rules
        from code_muse.model_factory import ModelFactory, make_model_settings
        from code_muse.model_utils import prepare_prompt_for_model

        # Resolve model
        model_name = model_override or self._resolve_model_name(expert)
        models_config = ModelFactory.load_config()

        if model_name not in models_config:
            raise ValueError(
                f"Model '{model_name}' not found in configuration — "
                "cannot create expert agent"
            )

        model = ModelFactory.get_model(model_name, models_config)

        # Build instructions
        instructions = _EXPERT_SYSTEM_PROMPT_TEMPLATE.format(
            expert_name=expert.name,
            speciality=expert.speciality,
            system_prompt_fragment=expert.system_prompt_fragment,
        )

        # Append AGENTS.md rules if available
        agent_rules = load_muse_rules()
        if agent_rules:
            instructions += f"\n\n{agent_rules}"

        # Append plugin prompt additions
        from code_muse import callbacks

        prompt_additions = callbacks.on_load_prompt()
        if prompt_additions:
            instructions += "\n" + "\n".join(
                str(p) for p in prompt_additions if p is not None
            )

        # Prepare for model (handles claude-code prepending etc.)
        prepared = prepare_prompt_for_model(
            model_name,
            instructions,
            "",  # user prompt is empty at build time
            prepend_system_to_user=False,
        )
        instructions = prepared.instructions

        model_settings = make_model_settings(model_name)

        # Build the pydantic-ai agent with ExpertReport output type
        temp_agent = PydanticAgent(
            model=model,
            instructions=instructions,
            output_type=ExpertReport,
            retries=2,
            # Explicitly restrict tools via registration later,
            # but ensure this agent has NO access to agent/browser control.
            toolsets=[],
            capabilities=[],
            model_settings=model_settings,
        )

        # Register read-only tools
        from code_muse.tools import register_tools_for_agent

        tools = list(READ_ONLY_TOOLS)
        register_tools_for_agent(temp_agent, tools, model_name=model_name)

        logger.debug(
            "ExpertAgentFactory: created agent for '%s' with tools=%s session=%s",
            expert.name,
            tools,
            session_id,
        )
        return temp_agent

    async def build_expert_pool(
        self,
        experts: list[ExpertDescriptor],
        request: AskMindPackInput,
        pool_config: MindPackExpertPoolConfig,
        session_id: str,
    ) -> list[tuple[ExpertDescriptor, PydanticAgent]]:
        """Spawns an asynchronous expert pool based on the configured mode."""
        spawn_mode = pool_config.spawn_mode

        if spawn_mode == "fixed":
            return await self._build_pool_fixed(
                experts,
                request,
                pool_config,
                session_id,
                count=pool_config.default_expert_count,
            )

        if spawn_mode == "adaptive":
            return await self._build_pool_fixed(
                experts,
                request,
                pool_config,
                session_id,
                count=pool_config.min_experts,
            )

        if spawn_mode == "same_agent_replicas":
            return await self._build_pool_same_agent_replicas(
                experts,
                request,
                pool_config,
                session_id,
            )

        if spawn_mode == "multi_model_replicas":
            return await self._build_pool_multi_model_replicas(
                experts,
                request,
                pool_config,
                session_id,
            )

        if spawn_mode == "hybrid":
            return await self._build_pool_hybrid(
                experts,
                request,
                pool_config,
                session_id,
            )

        if spawn_mode == "multi_agent":
            return await self._build_pool_multi_agent(
                experts,
                request,
                pool_config,
                session_id,
            )

        logger.warning(
            "Unknown spawn mode '%s'; falling back to fixed pool",
            spawn_mode,
        )
        return await self._build_pool_fixed(
            experts,
            request,
            pool_config,
            session_id,
            count=pool_config.default_expert_count,
        )

    async def _build_pool_fixed(
        self,
        experts: list[ExpertDescriptor],
        request: AskMindPackInput,
        pool_config: MindPackExpertPoolConfig,
        session_id: str,
        count: int | None = None,
    ) -> list[tuple[ExpertDescriptor, PydanticAgent]]:
        """Fixed-mode pool builder: spawn up to *count* agents from *experts*."""
        target_count = count if count is not None else pool_config.default_expert_count
        selected = experts[:target_count]
        if len(selected) < target_count:
            logger.warning(
                "Requested %d experts but registry only has %d; using all available",
                target_count,
                len(selected),
            )

        pool: list[tuple[ExpertDescriptor, PydanticAgent]] = []
        global_model = self._resolve_model_name(selected[0]) if selected else None

        for expert in selected:
            model_to_use = global_model
            if pool_config.model_strategy == "per_expert" and expert.model:
                model_to_use = expert.model
            elif pool_config.model_strategy == "model_pool":
                # Round-robin model rotation across experts
                if not hasattr(self, "_model_pool_index"):
                    self._model_pool_index = 0
                from code_muse.model_factory import ModelFactory

                models_config = ModelFactory.load_config()
                model_names = list(models_config.keys())
                if model_names:
                    model_to_use = model_names[
                        self._model_pool_index % len(model_names)
                    ]
                    self._model_pool_index += 1
                else:
                    model_to_use = global_model

            agent = self.create_expert_agent(
                expert,
                session_id=session_id,
                model_override=model_to_use,
            )
            pool.append((expert, agent))

        return pool

    async def _build_pool_same_agent_replicas(
        self,
        experts: list[ExpertDescriptor],
        request: AskMindPackInput,
        pool_config: MindPackExpertPoolConfig,
        session_id: str,
    ) -> list[tuple[ExpertDescriptor, PydanticAgent]]:
        """Spawn N copies of the first expert with different role lenses.

        Each replica gets a distinct lens (scout, architect, watchdog,
        test_planner, challenger) injected into its system prompt, providing
        diverse perspectives from a single base expert configuration.
        """
        if not experts:
            return []

        base = experts[0]
        count = min(pool_config.default_expert_count, pool_config.max_experts)
        lenses = ["scout", "architect", "watchdog", "test_planner", "challenger"]

        pool: list[tuple[ExpertDescriptor, PydanticAgent]] = []
        for i in range(count):
            lens = lenses[i % len(lenses)]
            variant = ExpertDescriptor(
                name=f"{base.name}-{lens}",
                speciality=f"{base.speciality} [{lens} lens]",
                system_prompt_fragment=(
                    f"LENS: {lens} perspective\n\n{base.system_prompt_fragment}"
                ),
                model=base.model,
                max_experts_override=base.max_experts_override,
            )
            model_name = self._resolve_model_name(base)
            agent = self.create_expert_agent(
                variant,
                session_id=session_id,
                model_override=model_name,
            )
            pool.append((variant, agent))

        logger.info(
            "same_agent_replicas: spawned %d replicas of '%s'",
            count,
            base.name,
        )
        return pool

    async def _build_pool_multi_model_replicas(
        self,
        experts: list[ExpertDescriptor],
        request: AskMindPackInput,
        pool_config: MindPackExpertPoolConfig,
        session_id: str,
    ) -> list[tuple[ExpertDescriptor, PydanticAgent]]:
        """Spawn experts across multiple models from the available model pool.

        Rotates through available models, assigning each expert a different
        model to get diverse LLM perspectives on the same problem.
        Falls back to fixed pool if no models are available.
        """
        if not experts:
            return []

        from code_muse.model_factory import ModelFactory

        models_config = ModelFactory.load_config()
        model_names = list(models_config.keys())

        if not model_names:
            logger.warning(
                "multi_model_replicas: no models available; falling back to fixed"
            )
            return await self._build_pool_fixed(
                experts,
                request,
                pool_config,
                session_id,
                count=pool_config.default_expert_count,
            )

        count = min(
            pool_config.default_expert_count,
            len(model_names),
            pool_config.max_experts,
        )

        pool: list[tuple[ExpertDescriptor, PydanticAgent]] = []
        for i in range(count):
            expert = experts[i % len(experts)]
            model_name = model_names[i % len(model_names)]

            variant = ExpertDescriptor(
                name=f"{expert.name}",
                speciality=expert.speciality,
                system_prompt_fragment=expert.system_prompt_fragment,
                model=model_name,
                max_experts_override=expert.max_experts_override,
            )
            agent = self.create_expert_agent(
                variant,
                session_id=session_id,
                model_override=model_name,
            )
            pool.append((variant, agent))

        logger.info(
            "multi_model_replicas: spawned %d experts across models: %s",
            count,
            model_names[:count],
        )
        return pool

    async def _build_pool_hybrid(
        self,
        experts: list[ExpertDescriptor],
        request: AskMindPackInput,
        pool_config: MindPackExpertPoolConfig,
        session_id: str,
    ) -> list[tuple[ExpertDescriptor, PydanticAgent]]:
        """Hybrid mode: fixed base + adaptive extras.

        Starts with a fixed base of min_experts, then adds adaptive bonus
        experts scaled by problem complexity (statement length heuristic).
        Caps at max_experts.
        """
        if not experts:
            return []

        fixed_base = min(pool_config.min_experts, len(experts))
        # Heuristic: +1 extra expert per 500 chars of problem statement, max +2
        problem_length = len(request.problem_statement)
        adaptive_bonus = min(2, problem_length // 500)
        total = min(fixed_base + adaptive_bonus, pool_config.max_experts, len(experts))

        logger.info(
            "hybrid: fixed_base=%d + adaptive_bonus=%d → total=%d experts",
            fixed_base,
            adaptive_bonus,
            total,
        )
        return await self._build_pool_fixed(
            experts,
            request,
            pool_config,
            session_id,
            count=total,
        )

    async def _build_pool_multi_agent(
        self,
        experts: list[ExpertDescriptor],
        request: AskMindPackInput,
        pool_config: MindPackExpertPoolConfig,
        session_id: str,
    ) -> list[tuple[ExpertDescriptor, PydanticAgent]]:
        """Multi-agent mode: attempts to load named agent configs per expert.

        For each expert, tries to load a matching agent from the agent
        manager. If the expert's name matches a registered agent, that
        agent's config/model are used. Otherwise falls back to the
        standard expert agent builder.

        This enables mixing MindPack experts with full Muse agents.
        """
        if not experts:
            return []

        from code_muse.agents.agent_manager import load_agent

        count = min(
            pool_config.default_expert_count, len(experts), pool_config.max_experts
        )
        selected = experts[:count]

        pool: list[tuple[ExpertDescriptor, PydanticAgent]] = []
        for expert in selected:
            # Try to load a matching named agent
            agent_config = None
            try:
                agent_config = load_agent(expert.name)
                logger.debug(
                    "multi_agent: loaded agent '%s' for expert '%s'",
                    expert.name,
                    expert.name,
                )
            except ValueError:
                logger.debug(
                    "multi_agent: no agent named '%s'; using standard expert agent",
                    expert.name,
                )

            # Use the agent's model if available, otherwise fall back
            model_name = expert.model or self._resolve_model_name(expert)
            if agent_config is not None:
                model_name = getattr(agent_config, "model", None) or model_name

            agent = self.create_expert_agent(
                expert,
                session_id=session_id,
                model_override=model_name,
            )
            pool.append((expert, agent))

        logger.info(
            "multi_agent: spawned %d experts (agent-mapped where available)",
            len(pool),
        )
        return pool

    async def invoke_expert(
        self,
        expert: ExpertDescriptor,
        request: AskMindPackInput,
        session_id: str,
    ) -> ExpertReport | None:
        """Run an expert agent and return its structured report.

        Returns ``None`` if the agent fails to produce a valid report.
        """
        group_id = f"mindpack-{expert.name}-{uuid.uuid4().hex[:6]}"

        try:
            temp_agent = self.create_expert_agent(
                expert, session_id=session_id, message_group=group_id
            )
        except ValueError as exc:
            logger.error(
                "ExpertAgentFactory: failed to create agent for '%s': %s",
                expert.name,
                exc,
            )
            return None

        user_prompt = build_expert_prompt(expert, request)

        return await self._run_expert(
            temp_agent=temp_agent,
            expert=expert,
            user_prompt=user_prompt,
            session_id=session_id,
            group_id=group_id,
        )

    # -- internal -----------------------------------------------------------

    @staticmethod
    def _resolve_model_name(expert: ExpertDescriptor) -> str:
        """Resolve the model name to use for expert agents.

        If the expert descriptor specifies a per-expert model override,
        use that.  Otherwise fall back to the global model name.
        """
        if expert.model:
            return expert.model

        from code_muse.config import get_global_model_name

        name = get_global_model_name()
        if not name:
            raise ValueError("No global model configured — cannot create expert agent")
        return name

    async def _run_expert(
        self,
        temp_agent: PydanticAgent,
        expert: ExpertDescriptor,
        user_prompt: str,
        session_id: str,
        group_id: str,
    ) -> ExpertReport | None:
        """Execute the expert agent in a subagent context.

        Handles streaming, cancellation, and error recovery.  Falls back
        to a text-parsed report if structured output fails.
        """
        from code_muse.agents.subagent_stream_handler import (
            subagent_stream_handler,
        )
        from code_muse.callbacks import on_agent_run_cancel, on_agent_run_context
        from code_muse.config import get_message_limit
        from code_muse.messaging import (
            SubAgentInvocationMessage,
            SubAgentResponseMessage,
            emit_success,
            get_message_bus,
        )

        bus = get_message_bus()

        # Emit invocation message for the console
        bus.emit(
            SubAgentInvocationMessage(
                agent_name=f"mindpack-{expert.name}",
                session_id=session_id,
                prompt=user_prompt[:200],
                is_new_session=True,
                message_count=0,
            )
        )

        stream_handler = partial(subagent_stream_handler, session_id=session_id)

        async with self._semaphore:
            with subagent_context(f"mindpack-{expert.name}"):
                run_ctxs = on_agent_run_context(
                    # Provide a minimal agent-like object for the hook
                    _MinimalAgentProxy(expert.name),
                    temp_agent,
                    group_id,
                )

                task = None
                try:
                    async with AsyncExitStack() as stack:
                        for cm in run_ctxs:
                            await stack.enter_async_context(cm)

                        task = asyncio.create_task(
                            temp_agent.run(
                                user_prompt,
                                message_history=[],
                                usage_limits=UsageLimits(
                                    request_limit=get_message_limit()
                                ),
                                event_stream_handler=stream_handler,
                            )
                        )

                        result = await task

                except asyncio.CancelledError:
                    if task and not task.done():
                        task.cancel()
                    await on_agent_run_cancel(group_id)
                    logger.warning(
                        "ExpertAgentFactory: expert '%s' cancelled", expert.name
                    )
                    return None

                except Exception as exc:
                    logger.error(
                        "ExpertAgentFactory: expert '%s' failed: %s",
                        expert.name,
                        exc,
                        exc_info=True,
                    )
                    return self._fallback_report(expert, session_id, str(exc))

        # Extract structured output
        report = self._extract_report(result, expert, session_id)

        # Emit completion message
        bus.emit(
            SubAgentResponseMessage(
                agent_name=f"mindpack-{expert.name}",
                session_id=session_id,
                response=report.summary[:200] if report else "",
                message_count=0,
            )
        )

        emit_success(
            f"✓ mindpack-{expert.name} completed",
            message_group=group_id,
        )

        return report

    @staticmethod
    def _extract_report(
        result: Any,
        expert: ExpertDescriptor,
        session_id: str,
    ) -> ExpertReport | None:
        """Extract an ExpertReport from the pydantic-ai result.

        Tries structured output first (``result.output``), then falls
        back to best-effort text parsing.
        """
        # Structured output path
        if result is not None and hasattr(result, "output"):
            output = result.output
            if isinstance(output, ExpertReport):
                # Ensure run_id is set correctly
                if output.run_id != session_id:
                    output = output.model_copy(update={"run_id": session_id})
                if output.expert_id != expert.name:
                    output = output.model_copy(update={"expert_id": expert.name})
                return output

            # If output is a dict, try to build ExpertReport from it
            if isinstance(output, dict):
                try:
                    report = ExpertReport(
                        expert_id=expert.name,
                        run_id=session_id,
                        **{
                            k: v
                            for k, v in output.items()
                            if k in ExpertReport.model_fields
                        },
                    )
                    return report
                except Exception:
                    pass

        # Text fallback — try to parse the raw output as text
        raw_text = ""
        if result is not None:
            if hasattr(result, "output"):
                raw_text = str(result.output)
            elif hasattr(result, "data"):
                raw_text = str(result.data)
            else:
                raw_text = str(result)

        if raw_text:
            return ExpertReport(
                expert_id=expert.name,
                run_id=session_id,
                lens="unknown",
                prompt_variant="fallback",
                summary=raw_text,
                findings=[],
                proposed_plan=[],
                risks=["Fallback: structured output not produced"],
                files_to_inspect=[],
                confidence=0.3,
                status="partial",
            )

        return None

    @staticmethod
    def _fallback_report(
        expert: ExpertDescriptor,
        session_id: str,
        error_msg: str,
    ) -> ExpertReport:
        """Build a minimal error report when the expert fails entirely."""
        return ExpertReport(
            expert_id=expert.name,
            run_id=session_id,
            lens="error",
            prompt_variant="fallback",
            summary=f"[Error] Expert '{expert.name}' failed: {error_msg}",
            findings=[],
            proposed_plan=[],
            risks=[f"Expert invocation failed: {error_msg}"],
            files_to_inspect=[],
            confidence=0.0,
            status="failed",
        )


# ---------------------------------------------------------------------------
# Minimal agent-like proxy for callback hooks
# ---------------------------------------------------------------------------


class _MinimalAgentProxy:
    """Lightweight object that satisfies the attribute requirements of
    ``on_agent_run_context`` and related hooks without needing a full
    ``BaseAgent`` instance.

    Expert agents are ephemeral — they don't have a real BaseAgent backing
    them, but some callback hooks expect an object with ``name`` and
    ``get_model_name()``.
    """

    def __init__(self, expert_name: str) -> None:
        self.name = f"mindpack-{expert_name}"
        self._model_name: str | None = None

    def get_model_name(self) -> str:
        if self._model_name is None:
            from code_muse.config import get_global_model_name

            self._model_name = get_global_model_name() or "unknown"
        return self._model_name
