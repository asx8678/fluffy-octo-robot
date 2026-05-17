"""Data models for smart output compressor."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


@dataclass
class CompressedNode:
    """A single node/block in the compressed output."""

    start_line: int
    end_line: int
    kind: Literal[
        "import", "function", "class", "decorator", "comment", "other", "omitted"
    ]
    name: str | None
    score: float  # 0.0–1.0 relevance
    content: str
    is_kept: bool = True  # False if elided


@dataclass
class CompressedOutput:
    """Result of compressing a source file."""

    file_path: str
    total_lines: int
    kept_lines: int
    nodes: list[CompressedNode]
    language: str
    used_fallback: bool
    raw_output: str  # The assembled output text

    @property
    def reduction_pct(self) -> float:
        if self.total_lines <= 0:
            return 0.0
        return (1 - self.kept_lines / self.total_lines) * 100


@dataclass
class CompressMetrics:
    """Aggregate compression metrics across calls."""

    total_files: int = 0
    total_lines_before: int = 0
    total_lines_after: int = 0
    reductions: list[float] = field(default_factory=list)

    @property
    def median_reduction_pct(self) -> float:
        if not self.reductions:
            return 0.0
        sorted_r = sorted(self.reductions)
        n = len(sorted_r)
        mid = n // 2
        if n % 2 == 0:
            return (sorted_r[mid - 1] + sorted_r[mid]) / 2
        return sorted_r[mid]

    def record(self, output: CompressedOutput) -> None:
        self.total_files += 1
        self.total_lines_before += output.total_lines
        self.total_lines_after += output.kept_lines
        self.reductions.append(output.reduction_pct)


# Module-level singleton for easy access
_metrics = CompressMetrics()


def get_metrics() -> CompressMetrics:
    """Return the global compression metrics singleton."""
    return _metrics
