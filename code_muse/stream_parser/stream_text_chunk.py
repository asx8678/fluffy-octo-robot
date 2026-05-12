"""Incremental parser result for one pushed chunk (or final flush)."""

from dataclasses import dataclass, field
from typing import TypeVar

T = TypeVar("T")


@dataclass
class StreamTextChunk[T]:
    """Result from feeding a text chunk to a StreamTextParser.

    Attributes:
        visible_text: Text safe to render immediately.
        extracted: Hidden payloads extracted from the chunk.
    """

    visible_text: str = ""
    extracted: list[T] = field(default_factory=list)

    def is_empty(self) -> bool:
        """Return True when no visible text or extracted payloads were produced."""
        return not self.visible_text and not self.extracted
