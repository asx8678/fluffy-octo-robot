"""Data models for the Universal Critic workflow."""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class TaskMetadata:
    """Metadata about a coding task for routing decisions."""

    original_prompt: str
    estimated_lines: int = 0
    estimated_complexity: str = "unknown"  # "trivial", "simple", "moderate", "complex"
    has_new_file_creation: bool = False
    has_shell_commands: bool = False
    has_multi_file_changes: bool = False
    routing_decision: str | None = None  # "light-coding-agent" or "heavy-coding-agent"
    originating_agent: str = "unknown"
    iteration_count: int = 0


@dataclass
class ReviewResult:
    """Result from Universal Code Critic review."""

    verdict: str  # "approved", "rejected", "flagged"
    summary: str = ""
    issues: list[str] = field(default_factory=list)
    suggestion: str | None = None
    raw_response: str | None = None


@dataclass
class AgentOutput:
    """Output from a coding agent, ready for review."""

    agent_name: str  # Must be exact: "heavy coding agent" or "light coding agent"
    originating_agent: str  # Internal routing name: "heavy-coding-agent" or
    # "light-coding-agent"
    file_paths: list[str] = field(default_factory=list)
    code_snippets: dict[str, str] = field(default_factory=dict)
    summary: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
