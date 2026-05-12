"""Parser for ``<proposed_plan>…</proposed_plan>`` line-based blocks.

Wraps :class:`TaggedLineParser` with a single tag spec and exposes a
:class:`StreamTextParser` interface that emits
:class:`ProposedPlanSegment` values.
"""

from dataclasses import dataclass
from enum import Enum
from typing import TypeVar

from code_muse.stream_parser.stream_text_chunk import StreamTextChunk
from code_muse.stream_parser.stream_text_parser import StreamTextParser
from code_muse.stream_parser.tagged_line_parser import (
    TaggedLineParser,
    TaggedLineSegment,
    TaggedLineSegmentNormal,
    TaggedLineSegmentTagDelta,
    TaggedLineSegmentTagEnd,
    TaggedLineSegmentTagStart,
    TagSpec,
)

T = TypeVar("T")


class ProposedPlanSegmentType(Enum):
    """Kind of segment produced by :class:`ProposedPlanParser`."""

    NORMAL = "normal"
    PLAN_START = "plan_start"
    PLAN_DELTA = "plan_delta"
    PLAN_END = "plan_end"


@dataclass
class ProposedPlanSegment:
    """Single semantic piece of a parsed assistant response.

    Attributes:
        type: Which kind of segment this is.
        text: Literal text content.  Only populated for ``NORMAL`` and
            ``PLAN_DELTA`` segments.
    """

    type: ProposedPlanSegmentType
    text: str = ""


class ProposedPlanParser(StreamTextParser[ProposedPlanSegment]):
    """Streaming parser that identifies ``<proposed_plan>`` blocks.

    Lines that exactly equal ``"<proposed_plan>"`` or ``"</proposed_plan>"``
    (after trimming) are removed from visible text and replaced by
    :class:`ProposedPlanSegment` boundary markers.  Content lines between
    those boundaries become ``PLAN_DELTA`` segments.  Everything else is
    ``NORMAL``.
    """

    def __init__(self) -> None:
        self._parser = TaggedLineParser(
            [TagSpec(open="<proposed_plan>", close="</proposed_plan>", tag="plan")]
        )

    def push_str(self, chunk: str) -> StreamTextChunk[ProposedPlanSegment]:
        """Feed a new text chunk.

        Args:
            chunk: Incoming text delta (may contain partial lines).

        Returns:
            Visible text outside plan blocks, plus any plan segments
            (``PLAN_START``, ``PLAN_DELTA``, ``PLAN_END``) extracted from
            the chunk.
        """
        segments = self._parser.parse(chunk)
        return self._build_chunk(segments)

    def finish(self) -> StreamTextChunk[ProposedPlanSegment]:
        """Flush any remaining buffered state.

        Unterminated plan blocks are auto-closed with a ``PLAN_END`` segment.

        Returns:
            Final visible text and any trailing plan segments.
        """
        segments = self._parser.finish()
        return self._build_chunk(segments)

    @staticmethod
    def _map_segment(seg: TaggedLineSegment) -> ProposedPlanSegment:
        """Convert a raw :class:`TaggedLineSegment` to a plan segment."""
        if isinstance(seg, TaggedLineSegmentNormal):
            return ProposedPlanSegment(ProposedPlanSegmentType.NORMAL, seg.text)
        if isinstance(seg, TaggedLineSegmentTagStart):
            return ProposedPlanSegment(ProposedPlanSegmentType.PLAN_START)
        if isinstance(seg, TaggedLineSegmentTagDelta):
            return ProposedPlanSegment(ProposedPlanSegmentType.PLAN_DELTA, seg.text)
        if isinstance(seg, TaggedLineSegmentTagEnd):
            return ProposedPlanSegment(ProposedPlanSegmentType.PLAN_END)
        # Exhaustive because TaggedLineSegment is a union of the four classes.
        raise TypeError(f"unexpected segment type: {type(seg)}")

    def _build_chunk(
        self, segments: list[TaggedLineSegment]
    ) -> StreamTextChunk[ProposedPlanSegment]:
        """Turn raw line segments into a :class:`StreamTextChunk`."""
        mapped = [self._map_segment(s) for s in segments]
        visible = "".join(
            s.text for s in mapped if s.type == ProposedPlanSegmentType.NORMAL
        )
        return StreamTextChunk(visible_text=visible, extracted=mapped)


def extract_proposed_plan_text(text: str) -> str | None:
    """Extract the raw plan text from a complete string.

    Runs the parser over the full text and concatenates all ``PLAN_DELTA``
    segments that appear inside ``PLAN_START`` / ``PLAN_END`` pairs.

    Args:
        text: Full assistant response text.

    Returns:
        The concatenated plan text, or ``None`` when no plan block is
        present.
    """
    parser = ProposedPlanParser()
    out = parser.push_str(text)
    tail = parser.finish()
    all_segments = out.extracted + tail.extracted

    parts: list[str] = []
    in_plan = False
    for seg in all_segments:
        if seg.type == ProposedPlanSegmentType.PLAN_START:
            in_plan = True
        elif seg.type == ProposedPlanSegmentType.PLAN_END:
            in_plan = False
        elif seg.type == ProposedPlanSegmentType.PLAN_DELTA and in_plan:
            parts.append(seg.text)

    return "".join(parts) if parts else None


def strip_proposed_plan_blocks(text: str) -> str:
    """Remove all ``<proposed_plan>…</proposed_plan>`` blocks from text.

    Args:
        text: Full assistant response text.

    Returns:
        Visible text with plan blocks and their content stripped.
    """
    parser = ProposedPlanParser()
    out = parser.push_str(text)
    tail = parser.finish()
    return out.visible_text + tail.visible_text
