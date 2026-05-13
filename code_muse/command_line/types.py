"""Shared type definitions for the command-line subsystem."""

from dataclasses import dataclass


@dataclass
class MarkdownCommandResult:
    """Result of a custom command that should be rendered as markdown.

    Attributes:
        content: The markdown string to display
        is_markdown: Always True for this type
    """

    content: str
    is_markdown: bool = True
