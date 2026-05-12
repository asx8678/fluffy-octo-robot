"""MindPack schemas — shared Pydantic models for cross-module use.

Breaks the circular dependency between ``orchestration.py`` and ``tools.py``
by keeping pure data models in a single importable location.

These models carry no logic — they are plain data contracts.
"""

from typing import Literal

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Expert descriptor
# ---------------------------------------------------------------------------


class ExpertDescriptor(BaseModel):
    """Metadata describing an expert that may be consulted."""

    name: str = Field(..., description="Unique expert identifier")
    speciality: str = Field(..., description="Domain of expertise")
    system_prompt_fragment: str = Field(
        default="",
        description="Prompt fragment injected into the expert's context",
    )
    max_experts_override: int | None = Field(
        default=None,
        description="If set, caps how many experts of this type to spawn",
    )
    model: str | None = Field(
        default=None,
        description="Optional custom model override for this specific expert",
    )


# ---------------------------------------------------------------------------
# Profile descriptor
# ---------------------------------------------------------------------------


class ProfileDescriptor(BaseModel):
    """A named bundle of expert names forming a reusable advisory panel."""

    name: str = Field(..., description="Unique profile identifier")
    description: str = Field(
        default="",
        description="Human-readable summary of what this profile is for",
    )
    expert_names: list[str] = Field(
        default_factory=list,
        description="Names of experts that belong to this profile",
    )


# ---------------------------------------------------------------------------
# AskMindPack I/O models
# ---------------------------------------------------------------------------


class MindPackRankedOption(BaseModel):
    """A single ranked option produced by the MindPack judge."""

    rank: int = Field(..., description="Ranking position (1 = best)")
    title: str = Field(..., description="Short title for this option")
    source_experts: list[str] = Field(
        default_factory=list,
        description="Expert names that contributed to this option",
    )
    summary: str = Field(..., description="One-paragraph summary of the option")
    pros: list[str] = Field(default_factory=list, description="Advantages")
    cons: list[str] = Field(default_factory=list, description="Disadvantages")
    risk: Literal["low", "medium", "high"] = Field(
        default="medium", description="Risk level"
    )
    confidence: float = Field(
        default=0.5, ge=0, le=1, description="Confidence score 0–1"
    )


class MindPackComparisonMatrix(BaseModel):
    consensus_points: list[str] = Field(default_factory=list)
    disagreements: list[str] = Field(default_factory=list)
    unsupported_claims: list[str] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    ranked_options: list[MindPackRankedOption] = Field(default_factory=list)


class MindPackMergedDecision(BaseModel):
    summary: str
    comparison: MindPackComparisonMatrix
    selected_option: MindPackRankedOption
    merged_plan_steps: list[str] = Field(default_factory=list)
    files_to_inspect_first: list[str] = Field(default_factory=list)
    files_expected_to_change: list[str] = Field(default_factory=list)
    tests_to_run: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    acceptance_criteria: list[str] = Field(default_factory=list)
    executor_instructions: str
    confidence: float = Field(default=0.5, ge=0, le=1)


class AskMindPackInput(BaseModel):
    """Input model for the ask_mindpack tool.

    Carries the executor's problem context so MindPack can spin up
    an appropriate expert pool.
    """

    problem_statement: str = Field(..., description="The specific problem to solve")
    current_goal: str = Field(
        ..., description="What the executor is currently trying to achieve"
    )
    current_plan: str | None = Field(default=None, description="Current plan, if any")
    what_has_been_tried: list[str] = Field(
        default_factory=list,
        description="Approaches already attempted",
    )
    relevant_files: list[str] = Field(
        default_factory=list,
        description="File paths relevant to the problem",
    )
    observed_errors: list[str] = Field(
        default_factory=list,
        description="Error messages or unexpected behaviours observed",
    )
    uncertainty: str | None = Field(
        default=None,
        description="What the executor is uncertain about",
    )
    desired_output: Literal[
        "plan",
        "review",
        "debug_strategy",
        "architecture_decision",
        "test_strategy",
        "compare_options",
    ] = Field(
        default="plan",
        description="Kind of advisory output the executor wants",
    )
    max_experts: int | None = Field(
        default=None,
        description="Cap on number of experts to consult",
    )


class AskMindPackOutput(BaseModel):
    """Output model for the ask_mindpack tool.

    Returns a merged, judge-vetted advisory response that the
    executor can use to continue its work.
    """

    summary: str = Field(..., description="High-level summary of the advisory")
    recommended_plan: str = Field(..., description="The judge-merged recommended plan")
    ranked_options: list[MindPackRankedOption] = Field(
        default_factory=list,
        description="Ranked alternative options from the expert pool",
    )
    risks: list[str] = Field(
        default_factory=list,
        description="Risks identified across all experts",
    )
    tests_to_run: list[str] = Field(
        default_factory=list,
        description="Suggested tests to validate the plan",
    )
    files_to_inspect_or_change: list[str] = Field(
        default_factory=list,
        description="Files the experts recommend inspecting or changing",
    )
    expert_consensus: str = Field(..., description="Summary of what experts agreed on")
    disagreements: list[str] = Field(
        default_factory=list,
        description="Key disagreements between experts",
    )
    confidence: float = Field(
        default=0.5,
        ge=0,
        le=1,
        description="Overall confidence in the recommendation",
    )


# ---------------------------------------------------------------------------
# MindPack V3 Configuration & Expert Models
# ---------------------------------------------------------------------------


ExpertSpawnMode = Literal[
    "fixed",
    "adaptive",
    "same_agent_replicas",
    "multi_model_replicas",
    "multi_agent",
    "hybrid",
]

ModelStrategy = Literal[
    "same_model",
    "model_pool",
    "per_expert",
]

ReportStoreMode = Literal[
    "memory",
    "cache",
    "workspace",
    "both",
]

MemoryScope = Literal[
    "run",
    "session",
    "project",
]


class MindPackExpertSpec(BaseModel):
    id: str
    agent: str | None = None
    model: str | None = None
    lens: str
    prompt_variant: str
    permissions: Literal["read_only"] = "read_only"
    max_model_requests: int = Field(default=8, ge=1, le=20)
    max_tool_calls: int = Field(default=20, ge=0, le=100)


class MindPackJudgeSpec(BaseModel):
    id: str = "judge"
    agent: str | None = None
    model: str | None = None
    lens: str = "compare_merge_rank"
    permissions: Literal["read_only"] = "read_only"
    max_model_requests: int = Field(default=6, ge=1, le=20)
    max_tool_calls: int = Field(default=10, ge=0, le=100)


class MindPackExpertPoolConfig(BaseModel):
    spawn_mode: ExpertSpawnMode = "fixed"
    default_expert_count: int = Field(default=5, ge=1, le=12)
    min_experts: int = Field(default=3, ge=1, le=12)
    max_experts: int = Field(default=7, ge=1, le=12)
    model_strategy: ModelStrategy = "same_model"
    experts: list[MindPackExpertSpec] = Field(default_factory=list)
    judge: MindPackJudgeSpec = Field(default_factory=MindPackJudgeSpec)


class MindPackReportStoreConfig(BaseModel):
    mode: ReportStoreMode = "memory"
    memory_scope: MemoryScope = "run"
    workspace_dir: str = ".mindpack/runs"
    cache_dir: str = "~/.muse/packmind/runs"
    save_raw_transcripts: bool = False


class MindPackNestedConfig(BaseModel):
    enabled: bool = True
    mode: Literal["advisory", "review", "debug"] = "advisory"
    max_depth: int = Field(default=1, ge=0, le=2)
    max_calls_per_prompt: int = Field(default=2, ge=0, le=10)
    timeout_sec: int = Field(default=90, ge=10, le=600)


class MindPackConfig(BaseModel):
    """Unified root configuration for MindPack V3.

    Wraps the three sub-config domains — expert pool, report storage,
    and nested (ask_mindpack) behaviour — into a single config object.
    """

    expert_pool: MindPackExpertPoolConfig = Field(
        default_factory=MindPackExpertPoolConfig,
        description="Expert pool spawning and model strategy settings",
    )
    report_store: MindPackReportStoreConfig = Field(
        default_factory=MindPackReportStoreConfig,
        description="Report storage mode and paths",
    )
    nested: MindPackNestedConfig = Field(
        default_factory=MindPackNestedConfig,
        description="Nested ask_mindpack workflow limits",
    )


DEFAULT_MINDPACK_CONFIG = MindPackConfig()


class MindPackExpertReport(BaseModel):
    run_id: str
    expert_id: str
    agent: str | None = None
    model: str | None = None
    lens: str
    prompt_variant: str
    status: Literal["success", "partial", "failed", "timeout"] = "success"
    summary: str
    findings: list[str] = Field(default_factory=list)
    proposed_plan: list[str] = Field(default_factory=list)
    files_to_inspect: list[str] = Field(default_factory=list)
    files_expected_to_change: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    tests_to_run: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.5, ge=0, le=1)


# ---------------------------------------------------------------------------
# Default profiles
# ---------------------------------------------------------------------------

_DEFAULT_PROFILES: list[ProfileDescriptor] = [
    ProfileDescriptor(
        name="Full Panel",
        description="All five default experts — full coverage",
        expert_names=[
            "Scout",
            "Architect",
            "Strategic Architect",
            "Systems Architect",
            "Pragmatic Architect",
            "Watchdog",
            "Test Planner",
            "Challenger",
        ],
    ),
    ProfileDescriptor(
        name="Security Audit",
        description="Focused on risk, security, and adversarial review",
        expert_names=["Watchdog", "Challenger"],
    ),
    ProfileDescriptor(
        name="Code Review",
        description="Design and testing focus for code review",
        expert_names=["Architect", "Test Planner"],
    ),
    ProfileDescriptor(
        name="Performance",
        description="Lean panel for quick performance analysis",
        expert_names=["Scout", "Watchdog"],
    ),
    ProfileDescriptor(
        name="Planning",
        description="Three architect perspectives — strategic, systems, and pragmatic — competing to produce the best plan",
        expert_names=[
            "Strategic Architect",
            "Systems Architect",
            "Pragmatic Architect",
        ],
    ),
    ProfileDescriptor(
        name="Default",
        description="Catch-all for experts not in any other profile",
        expert_names=[],
    ),
]
