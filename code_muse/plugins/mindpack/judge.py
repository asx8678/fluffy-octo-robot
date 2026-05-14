"""MindPack judge — LLM-backed report merging and AskMindPackOutput synthesis.

The judge reviews all expert reports, evaluates consensus and disagreement,
and produces the final unified advisory output.

Two components:

1. ``JudgeAgentFactory`` — creates a read-only "Judge" sub-agent that
   produces structured ``AskMindPackOutput`` from expert reports.
2. ``LLMJudgeMerger`` — concrete ``JudgeMerger`` that delegates to the
   factory, with a built-in fallback to placeholder logic on failure.

Both the judge agent and the merger degrade gracefully — the executor
always receives a valid ``AskMindPackOutput``, even if the LLM is down.
"""

import asyncio
import logging
import uuid
from contextlib import AsyncExitStack
from functools import partial
from typing import Any

from pydantic_ai import Agent as PydanticAgent
from pydantic_ai import UsageLimits

from code_muse.plugins.mindpack.orchestration import JudgeMerger
from code_muse.plugins.mindpack.schemas import (
    AskMindPackInput,
    AskMindPackOutput,
    MindPackRankedOption,
)
from code_muse.plugins.mindpack.schemas import (
    MindPackExpertReport as ExpertReport,
)
from code_muse.tools.subagent_context import subagent_context

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Read-only tool allow-list (same as experts — judge output is advisory)
# ---------------------------------------------------------------------------

JUDGE_READ_ONLY_TOOLS: list[str] = [
    "list_files",
    "read_file",
    "grep",
    "load_image_for_analysis",
    "list_or_search_skills",
]
"""Tools the judge may use.  All write-capable tools are deliberately excluded
to guarantee the judge never mutates the codebase."""

# ---------------------------------------------------------------------------
# Judge system prompt
# ---------------------------------------------------------------------------

_JUDGE_SYSTEM_PROMPT = """\
You are Judge, the deliberation synthesizer for the MindPack expert panel.

Your role is to review reports from multiple domain experts, identify areas
of consensus and disagreement, and produce a unified, actionable advisory
output that the executor can rely on.

## CRITICAL CONSTRAINTS

You are operating in **read-only advisory mode**. You must NEVER:
- Create, modify, or delete any files
- Run shell commands
- Invoke other agents or sub-agents
- Ask the user questions
- Navigate websites or use browser tools

You MAY: list/read files, search with grep, load images, list skills.

## YOUR TASK

You will receive:
1. The original consultation request (problem, goals, context)
2. Structured reports from experts, each with analysis, recommendations,
   risks, files, confidence, and disagreements.

You must:
1. **Identify consensus** — What do most or all experts agree on?
2. **Surface disagreements** — Where do experts diverge, and why?
3. **Synthesize recommendations** — Merge overlapping ones; resolve conflicts
   by weighing expert confidence and domain relevance; prefer simpler paths.
4. **Rank options** — Up to 3 ranked alternatives. Rank 1 = most recommended.
5. **Assess overall confidence** — Weighted average penalised for disagreements.
6. **Flag risks** — Consolidate, deduplicate, prioritise by severity.
7. **Recommend tests** — Concrete validation steps from the combined advice.

## SYNTHESIS GUIDELINES

- When experts agree, state consensus clearly and move on.
- When experts disagree, present both views in ``disagreements`` and pick
  the position supported by stronger reasoning or higher confidence.
- Never fabricate information not present in the expert reports.
- If an expert flagged a disagreement, explain both positions and justify
  the judge's resolution.
- Overall confidence should decrease when key experts disagree on core points.
- If only one expert was consulted, still produce a full output — but note
  the lack of cross-validation.

## OUTPUT FORMAT

You MUST produce a structured ``AskMindPackOutput`` with every field filled.
"""

# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------


def build_judge_prompt(
    request: AskMindPackInput,
    reports: list[ExpertReport],
) -> str:
    """Compose the user-facing prompt for the judge agent.

    Serialises the original request and expert reports into a structured
    format the judge can evaluate.
    """
    parts: list[str] = []

    # --- Original request ---
    parts.append("## ORIGINAL CONSULTATION REQUEST")
    parts.append(f"**Problem Statement:** {request.problem_statement}")
    parts.append(f"**Current Goal:** {request.current_goal}")
    if request.current_plan:
        parts.append(f"**Current Plan:** {request.current_plan}")
    if request.what_has_been_tried:
        parts.append(
            "**What Has Been Tried:**\n"
            + "\n".join(f"- {item}" for item in request.what_has_been_tried)
        )
    if request.relevant_files:
        parts.append(
            "**Relevant Files:**\n"
            + "\n".join(f"- {f}" for f in request.relevant_files)
        )
    if request.observed_errors:
        parts.append(
            "**Observed Errors:**\n"
            + "\n".join(f"- {e}" for e in request.observed_errors)
        )
    if request.uncertainty:
        parts.append(f"**Uncertainty:** {request.uncertainty}")
    parts.append(f"**Desired Output:** {request.desired_output}")

    # --- Expert reports ---
    parts.append(f"\n## EXPERT REPORTS ({len(reports)} total)")
    for i, report in enumerate(reports, 1):
        parts.append(f"\n### Report {i}: {report.expert_id}")
        parts.append(f"**Confidence:** {report.confidence:.2f}")
        parts.append(f"**Status:** {report.status}")
        parts.append(f"\n**Summary:**\n{report.summary}")
        if report.findings:
            parts.append(
                "**Findings:**\n" + "\n".join(f"- {f}" for f in report.findings)
            )
        if report.proposed_plan:
            parts.append(
                "**Proposed Plan:**\n"
                + "\n".join(f"- {p}" for p in report.proposed_plan)
            )
        if report.risks:
            parts.append("**Risks:**\n" + "\n".join(f"- {r}" for r in report.risks))
        if report.files_to_inspect:
            parts.append(
                "**Files to Inspect:**\n"
                + "\n".join(f"- {f}" for f in report.files_to_inspect)
            )

    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# JudgeAgentFactory
# ---------------------------------------------------------------------------


class JudgeAgentFactory:
    """Creates and runs a read-only Judge sub-agent that merges expert reports.

    Follows the same construction pattern as ``ExpertAgentFactory`` but
    outputs ``AskMindPackOutput`` instead of ``ExpertReport``.

    Usage::

        factory = JudgeAgentFactory()
        output = await factory.invoke_judge(request, reports, session_id)
    """

    def create_judge_agent(
        self,
        *,
        session_id: str,
        message_group: str | None = None,
    ) -> PydanticAgent:
        """Build a pydantic-ai agent for the judge.

        Configured with the judge system prompt, read-only tools, and
        ``AskMindPackOutput`` as the output type.  This is a temporary agent
        — not registered in the agent manager, does not persist.
        """
        from code_muse.agents._builder import load_muse_rules
        from code_muse.model_factory import ModelFactory, make_model_settings
        from code_muse.model_utils import prepare_prompt_for_model

        # Resolve model
        model_name = self._resolve_model_name()
        models_config = ModelFactory.load_config()

        if model_name not in models_config:
            raise ValueError(
                f"Model '{model_name}' not found in configuration — "
                "cannot create judge agent"
            )

        model = ModelFactory.get_model(model_name, models_config)

        # Build instructions
        instructions = _JUDGE_SYSTEM_PROMPT

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
            "",
            prepend_system_to_user=False,
        )
        instructions = prepared.instructions

        model_settings = make_model_settings(model_name)

        # Build the pydantic-ai agent with AskMindPackOutput output type
        judge_agent = PydanticAgent(
            model=model,
            instructions=instructions,
            output_type=AskMindPackOutput,
            retries=2,
            toolsets=[],
            capabilities=[],
            model_settings=model_settings,
        )

        # Register read-only tools
        from code_muse.tools import register_tools_for_agent

        tools = list(JUDGE_READ_ONLY_TOOLS)
        register_tools_for_agent(judge_agent, tools, model_name=model_name)

        logger.debug(
            "JudgeAgentFactory: created judge agent with tools=%s session=%s",
            tools,
            session_id,
        )
        return judge_agent

    async def invoke_judge(
        self,
        request: AskMindPackInput,
        reports: list[ExpertReport],
        session_id: str,
    ) -> AskMindPackOutput:
        """Run the judge agent and return the merged advisory output.

        Falls back to placeholder output if the judge fails entirely.
        """
        group_id = f"mindpack-judge-{uuid.uuid4().hex[:6]}"

        try:
            judge_agent = self.create_judge_agent(
                session_id=session_id, message_group=group_id
            )
        except ValueError as exc:
            logger.error("JudgeAgentFactory: failed to create judge agent: %s", exc)
            return self._placeholder_output(request, reports)

        user_prompt = build_judge_prompt(request, reports)

        return await self._run_judge(
            judge_agent=judge_agent,
            user_prompt=user_prompt,
            session_id=session_id,
            group_id=group_id,
            request=request,
            reports=reports,
        )

    # -- internal -----------------------------------------------------------

    @staticmethod
    def _resolve_model_name(model_name: str | None = None) -> str:
        """Resolve the model name for the judge agent.

        Resolution order:
        1. Explicit ``model_name`` override (caller-supplied, e.g. from a
           future registry or schema-driven config).
        2. ``packmind_judge_model`` key in the Muse INI config.
        3. Global model name from ``get_global_model_name()``.

        Raises ``ValueError`` if no model can be resolved.
        """
        # 1. Explicit caller override
        if model_name:
            return model_name

        # 2. Config-file override (packmind_judge_model in muse.cfg)
        from code_muse.config import get_value

        judge_model = get_value("packmind_judge_model")
        if judge_model:
            return judge_model

        # 3. Global fallback
        from code_muse.config import get_global_model_name

        name = get_global_model_name()
        if not name:
            raise ValueError("No global model configured — cannot create judge agent")
        return name

    async def _run_judge(
        self,
        judge_agent: PydanticAgent,
        user_prompt: str,
        session_id: str,
        group_id: str,
        request: AskMindPackInput,
        reports: list[ExpertReport],
    ) -> AskMindPackOutput:
        """Execute the judge agent in a subagent context."""
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

        bus.emit(
            SubAgentInvocationMessage(
                agent_name="mindpack-judge",
                session_id=session_id,
                prompt=user_prompt[:200],
                is_new_session=True,
                message_count=0,
            )
        )

        stream_handler = partial(subagent_stream_handler, session_id=session_id)

        with subagent_context("mindpack-judge"):
            run_ctxs = on_agent_run_context(
                _JudgeAgentProxy(),
                judge_agent,
                group_id,
            )

            task: asyncio.Task | None = None
            try:
                async with AsyncExitStack() as stack:
                    for cm in run_ctxs:
                        await stack.enter_async_context(cm)

                    task = asyncio.create_task(
                        judge_agent.run(
                            user_prompt,
                            message_history=[],
                            usage_limits=UsageLimits(request_limit=get_message_limit()),
                            event_stream_handler=stream_handler,
                        )
                    )

                    result = await task

            except asyncio.CancelledError:
                if task and not task.done():
                    task.cancel()
                await on_agent_run_cancel(group_id)
                logger.warning("JudgeAgentFactory: judge cancelled")
                return self._placeholder_output(request, reports)

            except Exception as exc:
                logger.error(
                    "JudgeAgentFactory: judge failed: %s",
                    exc,
                    exc_info=True,
                )
                return self._placeholder_output(request, reports)

        # Extract structured output
        output = self._extract_output(result, request, reports)

        # Emit completion message
        bus.emit(
            SubAgentResponseMessage(
                agent_name="mindpack-judge",
                session_id=session_id,
                response=output.summary[:200] if output else "",
                message_count=0,
            )
        )

        emit_success(
            "✓ mindpack-judge completed",
            message_group=group_id,
        )

        return output

    @staticmethod
    def _extract_output(
        result: Any,
        request: AskMindPackInput,
        reports: list[ExpertReport],
    ) -> AskMindPackOutput:
        """Extract ``AskMindPackOutput`` from the pydantic-ai result.

        Tries structured output, then dict coercion, then placeholder.
        """
        if result is not None and hasattr(result, "output"):
            output = result.output
            if isinstance(output, AskMindPackOutput):
                return output

            # Dict path — model returned raw dict instead of model instance
            if isinstance(output, dict):
                try:
                    return AskMindPackOutput(
                        **{
                            k: v
                            for k, v in output.items()
                            if k in AskMindPackOutput.model_fields
                        }
                    )
                except Exception:
                    pass

        # Final fallback
        return JudgeAgentFactory._placeholder_output(request, reports)

    @staticmethod
    def _placeholder_output(
        request: AskMindPackInput,
        reports: list[ExpertReport],
    ) -> AskMindPackOutput:
        """Build a placeholder output when the judge cannot produce one.

        Mirrors ``PlaceholderJudgeMerger`` for graceful degradation.
        """
        expert_names = [r.expert_id for r in reports]
        all_risks = [r for report in reports for r in report.risks]
        all_files = [f for report in reports for f in report.files_to_inspect]
        all_recs = [r for report in reports for r in report.proposed_plan]

        return AskMindPackOutput(
            summary=(
                f"Judge fallback: consulted {len(reports)} expert(s) "
                f"for '{request.desired_output}' on: "
                f"{request.problem_statement[:200]}"
            ),
            recommended_plan=("\n".join(all_recs) or "No recommendations produced."),
            ranked_options=[
                MindPackRankedOption(
                    rank=1,
                    title="Fallback option",
                    source_experts=expert_names,
                    summary=("Judge LLM failed — merged option from raw expert data."),
                )
            ],
            risks=all_risks or ["No risks identified (judge fallback)."],
            tests_to_run=[],
            files_to_inspect_or_change=list(dict.fromkeys(all_files)),
            expert_consensus=(f"Fallback: {len(reports)} expert(s) consulted."),
            disagreements=[],
            confidence=(sum(r.confidence for r in reports) / max(len(reports), 1)),
        )


# ---------------------------------------------------------------------------
# Minimal agent proxy for callback hooks
# ---------------------------------------------------------------------------


class _JudgeAgentProxy:
    """Lightweight proxy for ``on_agent_run_context`` callback hooks."""

    def __init__(self) -> None:
        self.name = "mindpack-judge"
        self._model_name: str | None = None

    def get_model_name(self) -> str:
        if self._model_name is None:
            self._model_name = JudgeAgentFactory._resolve_model_name() or "unknown"
        return self._model_name


# ---------------------------------------------------------------------------
# LLMJudgeMerger
# ---------------------------------------------------------------------------


class LLMJudgeMerger(JudgeMerger):
    """Concrete ``JudgeMerger`` that delegates merging to an LLM judge.

    Falls back to placeholder-style merging if the judge fails, so the
    orchestrator always receives a valid ``AskMindPackOutput``.
    """

    def __init__(
        self,
        factory: JudgeAgentFactory | None = None,
    ) -> None:
        self._factory = factory or JudgeAgentFactory()

    async def merge(
        self,
        request: AskMindPackInput,
        reports: list[ExpertReport],
        session_id: str,
    ) -> AskMindPackOutput:
        """Produce a unified advisory from all expert reports via LLM judge.

        Degrades to placeholder merge if the judge fails.
        """
        if not reports:
            return self._empty_output(request)

        try:
            return await self._factory.invoke_judge(request, reports, session_id)
        except Exception as exc:
            logger.error(
                "LLMJudgeMerger: judge invocation failed, using fallback: %s",
                exc,
                exc_info=True,
            )
            return JudgeAgentFactory._placeholder_output(request, reports)

    @staticmethod
    def _empty_output(request: AskMindPackInput) -> AskMindPackOutput:
        """Minimal output when no expert reports are available."""
        return AskMindPackOutput(
            summary=(f"No expert reports available for '{request.desired_output}'."),
            recommended_plan=("Unable to produce a plan — no experts consulted."),
            ranked_options=[],
            risks=["No experts were consulted — advice is unvalidated."],
            tests_to_run=[],
            files_to_inspect_or_change=list(request.relevant_files),
            expert_consensus="N/A — no reports received.",
            disagreements=[],
            confidence=0.0,
        )
