"""MindPack tools — ask_mindpack tool and orchestrator wiring.

Initialises a singleton MindPackOrchestrator with the five default
experts and registers the advisory deep-solve tool via the plugin
hook system.  Data models live in ``schemas.py`` to avoid circular
imports between this module and ``orchestration.py``.

Nested-workflow safety (Epic 5 & 6):
- ``MindPackInvocationContext`` tracks per-prompt call counts and depth.
- ``ask_mindpack`` cannot be called recursively (max_depth defaults to 1).
- ``max_calls_per_prompt`` prevents execution loops.
"""

import logging
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Literal

from pydantic_ai import RunContext

from code_muse.plugins.mindpack.orchestration import MindPackOrchestrator
from code_muse.plugins.mindpack.schemas import (
    AskMindPackInput,
    AskMindPackOutput,
    ExpertDescriptor,
    MindPackNestedConfig,
    MindPackRankedOption,
)

# Backward-compatible re-exports — external code importing from
# ``tools`` still works, but canonical location is ``schemas``.
__all__ = [
    "AskMindPackInput",
    "AskMindPackOutput",
    "ExpertDescriptor",
    "MindPackRankedOption",
    "MindPackInvocationContext",
    "register_ask_mindpack",
]

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# INI config helpers (local copy to avoid cross-module import cycles)
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
        return default


def _get_config_bool(key: str, default: bool) -> bool:
    from code_muse.config import get_value

    val = get_value(key)
    if val is None:
        return default
    return str(val).lower() in ("1", "true", "yes", "on")


def load_nested_config_from_ini() -> MindPackNestedConfig:
    """Build a ``MindPackNestedConfig`` from INI settings.

    Reads ``packmind_nested_enabled``, ``packmind_nested_max_depth``,
    ``packmind_nested_max_calls_per_prompt``, and
    ``packmind_nested_timeout_sec`` from the Muse INI config.
    """
    return MindPackNestedConfig(
        enabled=_get_config_bool("packmind_nested_enabled", True),
        max_depth=_get_config_int("packmind_nested_max_depth", 1),
        max_calls_per_prompt=_get_config_int("packmind_nested_max_calls_per_prompt", 2),
        timeout_sec=_get_config_int("packmind_nested_timeout_sec", 90),
    )


# ---------------------------------------------------------------------------
# MindPackInvocationContext — nested-workflow guardrails
# ---------------------------------------------------------------------------


@dataclass
class MindPackInvocationContext:
    """Runtime context for a single MindPack invocation.

    Tracks nesting depth (to prevent recursive ``ask_mindpack`` calls)
    and the number of invocations already made in the current prompt
    (to enforce ``max_calls_per_prompt``).
    """

    nested_depth: int = 0
    max_depth: int = 1
    max_calls_per_prompt: int = 2
    session_id: str | None = None
    call_count: int = field(default=0, repr=False)

    def is_recursion_blocked(self) -> bool:
        """True if we are already inside a MindPack call (depth ≥ 1)."""
        return self.nested_depth >= self.max_depth

    def is_call_limit_reached(self) -> bool:
        """True if the per-prompt call cap has been exceeded."""
        return self.call_count >= self.max_calls_per_prompt

    def increment_call(self) -> None:
        self.call_count += 1
        self.nested_depth += 1


# ContextVar tracking the *current* invocation (None when outside ask_mindpack)
_mindpack_ctx_var: ContextVar[MindPackInvocationContext | None] = ContextVar(
    "mindpack_ctx", default=None
)

# ContextVar tracking how many times ask_mindpack has been called in this prompt
_mindpack_call_count_var: ContextVar[int] = ContextVar("mindpack_call_count", default=0)


def _check_and_increment_call(
    nested_config: MindPackNestedConfig,
) -> MindPackInvocationContext:
    """Validate recursion / call-count guardrails and return a fresh context.

    Raises:
        RuntimeError: with an explicit rejection message if recursion limits
        or the per-prompt call cap are exceeded.
    """
    # 1. Check if we are already inside a MindPack invocation (recursion)
    existing_ctx = _mindpack_ctx_var.get()
    if existing_ctx is not None:
        raise RuntimeError(
            "❌ MindPack recursion blocked: ask_mindpack cannot be called recursively. "
            f"Current nested_depth={existing_ctx.nested_depth}, max_depth={existing_ctx.max_depth}. "
            "Experts are already running in advisory mode; invoking another MindPack panel "
            "inside an active consultation would create an infinite loop."
        )

    # 2. Check per-prompt call count
    current_calls = _mindpack_call_count_var.get()
    if current_calls >= nested_config.max_calls_per_prompt:
        raise RuntimeError(
            "❌ MindPack call-limit reached: ask_mindpack has already been invoked "
            f"{current_calls} time(s) in this prompt (max_calls_per_prompt="
            f"{nested_config.max_calls_per_prompt}). To prevent execution loops, "
            "further MindPack calls are blocked for the remainder of this turn."
        )

    # 3. Increment counters and build a new context
    call_token = _mindpack_call_count_var.set(current_calls + 1)
    new_ctx = MindPackInvocationContext(
        nested_depth=1,
        max_depth=nested_config.max_depth,
        max_calls_per_prompt=nested_config.max_calls_per_prompt,
        call_count=current_calls + 1,
    )
    ctx_token = _mindpack_ctx_var.set(new_ctx)

    # Return tokens so the caller can reset them in a finally block
    new_ctx._call_token = call_token  # type: ignore[attr-defined]
    new_ctx._ctx_token = ctx_token  # type: ignore[attr-defined]
    return new_ctx


def _reset_context(ctx: MindPackInvocationContext) -> None:
    """Reset ContextVars after a MindPack invocation finishes."""
    try:
        _mindpack_ctx_var.reset(ctx._ctx_token)  # type: ignore[attr-defined]
    except Exception:
        pass
    try:
        _mindpack_call_count_var.reset(ctx._call_token)  # type: ignore[attr-defined]
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Singleton orchestrator + default expert registration
# ---------------------------------------------------------------------------

orchestrator = MindPackOrchestrator()

_DEFAULT_EXPERTS: list[ExpertDescriptor] = [
    ExpertDescriptor(
        name="Scout",
        speciality="codebase exploration & context gathering",
        model="fast",
        system_prompt_fragment=(
            "You are Scout, the codebase explorer. Your job is to quickly "
            "scan relevant files, trace dependencies, and surface the "
            "context needed to understand a problem. Focus on what exists "
            "and how it connects."
        ),
    ),
    ExpertDescriptor(
        name="Architect",
        speciality="design & architecture decisions",
        model="strong",
        system_prompt_fragment=(
            "You are Architect, the design thinker. Your job is to "
            "propose clean structural solutions, weigh trade-offs, "
            "and ensure the plan fits the existing codebase architecture."
        ),
    ),
    ExpertDescriptor(
        name="Strategic Architect",
        speciality="big-picture architecture & long-term vision",
        model="strong",
        system_prompt_fragment=(
            "You are Strategic Architect, the big-picture thinker. Your job is to "
            "step back and design the long-term architecture — system boundaries, "
            "module ownership, technology choices, and how the plan fits the "
            "project's 6-month roadmap. Think in terms of maintainability, "
            "scalability, and technical debt avoidance. Propose the ideal end-state "
            "and work backwards to a phased delivery plan."
        ),
    ),
    ExpertDescriptor(
        name="Systems Architect",
        speciality="component integration & data flow design",
        model="strong",
        system_prompt_fragment=(
            "You are Systems Architect, the integration specialist. Your job is to "
            "design how components communicate — API contracts, data models, event "
            "flows, and service boundaries. Focus on the seams between modules: "
            "what data moves where, what interfaces need to change, and how to "
            "minimize coupling. Your plans should make the integration surface "
            "explicit and testable."
        ),
    ),
    ExpertDescriptor(
        name="Pragmatic Architect",
        speciality="incremental delivery & risk-aware planning",
        model="strong",
        system_prompt_fragment=(
            "You are Pragmatic Architect, the delivery-focused planner. Your job is "
            "to find the smallest viable change that moves the needle. You balance "
            "idealism with reality — prefer incremental refactors over rewrites, "
            "identify what can be deferred, and always have a rollback strategy. "
            "Your plans prioritize developer velocity, reversibility, and "
            "shipping value early."
        ),
    ),
    ExpertDescriptor(
        name="Watchdog",
        speciality="risk assessment & edge-case analysis",
        model="medium",
        system_prompt_fragment=(
            "You are Watchdog, the risk analyst. Your job is to "
            "identify failure modes, security concerns, edge cases, "
            "and anything that could go wrong with a proposed plan."
        ),
    ),
    ExpertDescriptor(
        name="Test Planner",
        speciality="validation strategy & test design",
        model="medium",
        system_prompt_fragment=(
            "You are Test Planner, the validation strategist. Your job is "
            "to design the smallest effective test suite that confirms "
            "the plan works and catches regressions."
        ),
    ),
    ExpertDescriptor(
        name="Challenger",
        speciality="adversarial review & assumption questioning",
        model="strong",
        system_prompt_fragment=(
            "You are Challenger, the adversarial reviewer. Your job is "
            "to poke holes in every proposal, question assumptions, "
            "and argue for simpler alternatives when they exist."
        ),
    ),
]

orchestrator.register_experts(_DEFAULT_EXPERTS)
orchestrator.load_experts()  # Load any custom experts from disk
orchestrator.load_profiles()  # Load profiles (seeds defaults on first run)

logger.info(
    "MindPack orchestrator initialised with %d default expert(s): %s",
    len(_DEFAULT_EXPERTS),
    [e.name for e in _DEFAULT_EXPERTS],
)

# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------


def register_ask_mindpack(agent):
    """Register the ask_mindpack tool on the given agent."""

    @agent.tool
    async def ask_mindpack(
        context: RunContext,
        problem_statement: str,
        current_goal: str,
        current_plan: str | None = None,
        what_has_been_tried: list[str] | None = None,
        relevant_files: list[str] | None = None,
        observed_errors: list[str] | None = None,
        uncertainty: str | None = None,
        desired_output: Literal[
            "plan",
            "review",
            "debug_strategy",
            "architecture_decision",
            "test_strategy",
            "compare_options",
        ] = "plan",
        max_experts: int | None = None,
    ) -> AskMindPackOutput:
        """Request a deep advisory analysis from the MindPack expert pool.

        Use this tool when you encounter a problem that needs deeper
        reasoning, multiple expert perspectives, or comparison of
        approaches.  MindPack runs in nested advisory mode: experts
        are read-only, make no file edits, and cannot call ask_mindpack
        recursively.

        Do NOT call this for simple edits or direct user requests
        that require only a single obvious action.

        Args:
            problem_statement: The specific problem to solve.
            current_goal: What you are currently trying to achieve.
            current_plan: Your current plan, if any.
            what_has_been_tried: Approaches already attempted.
            relevant_files: File paths relevant to the problem.
            observed_errors: Error messages or unexpected behaviours.
            uncertainty: What you are uncertain about.
            desired_output: Kind of advisory output you want.
            max_experts: Cap on number of experts to consult.
        """
        nested_config = load_nested_config_from_ini()

        # Epic 5 & 6 — enforce nested-workflow guardrails
        invocation_ctx = _check_and_increment_call(nested_config)
        try:
            logger.info(
                "ask_mindpack invoked: desired_output=%s, problem=%s "
                "depth=%d/%d calls=%d/%d",
                desired_output,
                problem_statement[:120],
                invocation_ctx.nested_depth,
                invocation_ctx.max_depth,
                invocation_ctx.call_count,
                invocation_ctx.max_calls_per_prompt,
            )

            request = AskMindPackInput(
                problem_statement=problem_statement,
                current_goal=current_goal,
                current_plan=current_plan,
                what_has_been_tried=what_has_been_tried or [],
                relevant_files=relevant_files or [],
                observed_errors=observed_errors or [],
                uncertainty=uncertainty,
                desired_output=desired_output,
                max_experts=max_experts,
            )

            # Run orchestration with invocation context so the orchestrator
            # knows it is inside a nested workflow (e.g., for timeout caps).
            raw_output = await orchestrator.consult(
                request,
                invocation_context=invocation_ctx,
                nested_config=nested_config,
            )
            return raw_output
        finally:
            _reset_context(invocation_ctx)

    return ask_mindpack
