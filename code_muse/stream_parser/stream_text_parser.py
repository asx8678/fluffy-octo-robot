"""Abstract base class for composable streaming text parsers."""

from abc import ABC, abstractmethod
from typing import TypeVar

from code_muse.stream_parser.stream_text_chunk import StreamTextChunk

T = TypeVar("T")


class StreamTextParser[T](ABC):
    """Base class for parsers that consume streamed text and emit visible text
    plus extracted payloads.

    Parsers are composable: one parser can wrap another, delegating and
    merging output.
    """

    @abstractmethod
    def push_str(self, chunk: str) -> StreamTextChunk[T]:
        """Feed a new text chunk. Returns visible text + extracted payloads."""
        ...

    @abstractmethod
    def finish(self) -> StreamTextChunk[T]:
        """Flush any buffered state at end-of-stream (or end-of-item)."""
        ...
