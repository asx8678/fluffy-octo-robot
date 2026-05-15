"""Data models for the Context-Aware Code Reader plugin."""

from dataclasses import dataclass
from typing import Literal


@dataclass
class CodeSection:
    """A contiguous relevant section of a source file."""

    start_line: int  # 1-based, inclusive
    end_line: int  # 1-based, inclusive
    kind: Literal["import", "function", "class", "other"]
    name: str | None
    score: float
    content: str


@dataclass
class RelevanceResult:
    """Result of running the AST relevance engine on a file."""

    file_path: str
    total_lines: int
    sections: list[CodeSection]
    used_fallback: bool = False
    language: str | None = None
