"""Stream parser for <oai-mem-citation> tags."""

from code_muse.stream_parser.inline_hidden_tag_parser import (
    InlineHiddenTagParser,
    InlineTagSpec,
)
from code_muse.stream_parser.stream_text_chunk import StreamTextChunk
from code_muse.stream_parser.stream_text_parser import StreamTextParser

CITATION_OPEN = "<oai-mem-citation>"
CITATION_CLOSE = "</oai-mem-citation>"


class CitationStreamParser(StreamTextParser[str]):
    """Stream parser for ``<oai-mem-citation>…</oai-mem-citation>`` tags.

    Thin wrapper around :class:`InlineHiddenTagParser` that returns citation
    bodies as plain strings and omits the citation tags from visible text.
    Matching is literal and non-nested.  Unterminated tags auto-close at
    :meth:`finish`.
    """

    def __init__(self) -> None:
        self._inner = InlineHiddenTagParser(
            [InlineTagSpec("citation", CITATION_OPEN, CITATION_CLOSE)]
        )

    def push_str(self, chunk: str) -> StreamTextChunk[str]:
        """Feed a new text chunk.

        Args:
            chunk: Incoming assistant text delta.

        Returns:
            Visible text with citation tags stripped, plus any citation
            payloads extracted from the chunk.
        """
        inner = self._inner.push_str(chunk)
        return StreamTextChunk(
            visible_text=inner.visible_text,
            extracted=[tag.content for tag in inner.extracted],
        )

    def finish(self) -> StreamTextChunk[str]:
        """Flush any buffered state.

        Unterminated citation tags are auto-closed and their accumulated
        content is returned as a citation payload.

        Returns:
            Final visible text and any trailing citations.
        """
        inner = self._inner.finish()
        return StreamTextChunk(
            visible_text=inner.visible_text,
            extracted=[tag.content for tag in inner.extracted],
        )


def strip_citations(text: str) -> tuple[str, list[str]]:
    """Strip citation tags from a complete string.

    Args:
        text: Full assistant response text.

    Returns:
        ``(visible_text, citations)`` where ``visible_text`` has all
        ``<oai-mem-citation>…</oai-mem-citation>`` blocks removed and
        ``citations`` is the list of extracted citation bodies.
    """
    parser = CitationStreamParser()
    out = parser.push_str(text)
    tail = parser.finish()
    visible = out.visible_text + tail.visible_text
    citations = out.extracted + tail.extracted
    return visible, citations
