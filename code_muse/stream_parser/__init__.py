"""Streaming text parsers for assistant markup.

This module ports Codex's Rust ``utils/stream-parser`` crate to idiomatic
Python 3.11+.  Parsers are composable: one parser can wrap another,
delegating and merging output.
"""

from code_muse.stream_parser.assistant_text_parser import (
    AssistantTextChunk,
    AssistantTextStreamParser,
)
from code_muse.stream_parser.citation_parser import (
    CITATION_CLOSE,
    CITATION_OPEN,
    CitationStreamParser,
    strip_citations,
)
from code_muse.stream_parser.inline_hidden_tag_parser import (
    ExtractedInlineTag,
    InlineHiddenTagParser,
    InlineTagSpec,
)
from code_muse.stream_parser.proposed_plan_parser import (
    ProposedPlanParser,
    ProposedPlanSegment,
    ProposedPlanSegmentType,
    extract_proposed_plan_text,
    strip_proposed_plan_blocks,
)
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
from code_muse.stream_parser.utf8_stream_parser import (
    IncompleteUtf8AtEof,
    InvalidUtf8,
    Utf8StreamParser,
    Utf8StreamParserError,
)

__all__ = [
    "AssistantTextChunk",
    "AssistantTextStreamParser",
    "CITATION_CLOSE",
    "CITATION_OPEN",
    "CitationStreamParser",
    "ExtractedInlineTag",
    "IncompleteUtf8AtEof",
    "InlineHiddenTagParser",
    "InlineTagSpec",
    "InvalidUtf8",
    "ProposedPlanParser",
    "ProposedPlanSegment",
    "ProposedPlanSegmentType",
    "StreamTextChunk",
    "StreamTextParser",
    "TagSpec",
    "TaggedLineParser",
    "TaggedLineSegment",
    "TaggedLineSegmentNormal",
    "TaggedLineSegmentTagDelta",
    "TaggedLineSegmentTagEnd",
    "TaggedLineSegmentTagStart",
    "Utf8StreamParser",
    "Utf8StreamParserError",
    "extract_proposed_plan_text",
    "strip_citations",
    "strip_proposed_plan_blocks",
]
