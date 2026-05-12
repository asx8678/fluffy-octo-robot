"""Combined assistant text parser: citations + plan segments in one pass."""

from dataclasses import dataclass, field

from code_muse.stream_parser.citation_parser import CitationStreamParser
from code_muse.stream_parser.proposed_plan_parser import (
    ProposedPlanParser,
    ProposedPlanSegment,
)


@dataclass
class AssistantTextChunk:
    """Result chunk from :class:`AssistantTextStreamParser`.

    Attributes:
        visible_text: Text safe to render immediately (tags stripped).
        citations: Citation bodies extracted in this chunk.
        plan_segments: Plan boundary / delta segments when plan mode is on.
    """

    visible_text: str = ""
    citations: list[str] = field(default_factory=list)
    plan_segments: list[ProposedPlanSegment] = field(default_factory=list)

    def is_empty(self) -> bool:
        """Return True when nothing was produced in this chunk."""
        return not self.visible_text and not self.citations and not self.plan_segments


class AssistantTextStreamParser:
    """Parses assistant text streaming markup in one pass.

    Strips ``<oai-mem-citation>`` tags and extracts citation payloads.
    In plan mode, also strips ``<proposed_plan>`` blocks and emits plan
    segments so callers can render or hide plan content independently.

    The two sub-parsers are wired in series: incoming text first goes through
    :class:`CitationStreamParser`; the resulting visible text is then fed into
    :class:`ProposedPlanParser` when plan mode is enabled.
    """

    def __init__(self, plan_mode: bool = False) -> None:
        self.plan_mode = plan_mode
        self._citations = CitationStreamParser()
        self._plan = ProposedPlanParser()

    def push_str(self, chunk: str) -> AssistantTextChunk:
        """Feed a new text chunk.

        Args:
            chunk: Raw assistant text delta.

        Returns:
            Chunk containing visible text, any newly-extracted citations, and
            any plan segments when plan mode is enabled.
        """
        citation_chunk = self._citations.push_str(chunk)
        out = self._parse_visible_text(citation_chunk.visible_text)
        out.citations = citation_chunk.extracted
        return out

    def finish(self) -> AssistantTextChunk:
        """Flush any buffered state.

        Unterminated citations and plan blocks are auto-closed.

        Returns:
            Final chunk with trailing visible text, citations, and plan
            segments.
        """
        citation_chunk = self._citations.finish()
        out = self._parse_visible_text(citation_chunk.visible_text)
        if self.plan_mode:
            tail = self._plan.finish()
            if not tail.is_empty():
                out.visible_text += tail.visible_text
                out.plan_segments.extend(tail.extracted)
        out.citations = citation_chunk.extracted
        return out

    def _parse_visible_text(self, visible_text: str) -> AssistantTextChunk:
        """Route citation-visible text through the plan parser when needed."""
        if not self.plan_mode:
            return AssistantTextChunk(visible_text=visible_text)
        plan_chunk = self._plan.push_str(visible_text)
        return AssistantTextChunk(
            visible_text=plan_chunk.visible_text,
            plan_segments=plan_chunk.extracted,
        )
