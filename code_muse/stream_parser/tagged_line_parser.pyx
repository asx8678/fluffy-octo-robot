# cython: language_level=3
"""Line-based tag-block parser for streamed text.

A tag must appear alone on a line after trimming (e.g.
``"<proposed_plan>"`` or ``"</proposed_plan>"``).  Lines inside a tag block
are emitted as :class:`TaggedLineSegmentTagDelta`; lines outside are emitted as
:class:`TaggedLineSegmentNormal`.

The parser buffers text until it can disprove that the current partial line is
a tag line—once the trimmed prefix is no longer a prefix of any known open or
close delimiter, the line is emitted immediately so that visible text is not
held back unnecessarily.
"""

from dataclasses import dataclass
from typing import Any


@dataclass
class TagSpec:
    """Specification for a line-based tag block.

    Attributes:
        open: Exact opening line text (e.g. ``"<proposed_plan>"``).
        close: Exact closing line text (e.g. ``"</proposed_plan>"``).
        tag: Tag identifier emitted in segment results.
    """

    open: str
    close: str
    tag: Any


@dataclass
class TaggedLineSegmentNormal:
    """Plain text that lives outside any tag block."""

    text: str


@dataclass
class TaggedLineSegmentTagStart:
    """Emitted when a line exactly matches a tag's ``open`` delimiter."""

    tag: Any


@dataclass
class TaggedLineSegmentTagDelta:
    """Text that belongs inside an open tag block.

    Consecutive deltas with the same tag are coalesced by the parser.
    """

    tag: Any
    text: str


@dataclass
class TaggedLineSegmentTagEnd:
    """Emitted when a line exactly matches a tag's ``close`` delimiter."""

    tag: Any


TaggedLineSegment = (
    TaggedLineSegmentNormal
    | TaggedLineSegmentTagStart
    | TaggedLineSegmentTagDelta
    | TaggedLineSegmentTagEnd
)


class TaggedLineParser:
    """Streaming line-based tag-block parser.

    * Buffers partial lines and emits them only once they can no longer be a
      tag line (the trimmed prefix is not a prefix of any open or close).
    * Complete lines (ending in ``\\n``) are classified immediately.
    * Tag lines are stripped from visible output and replaced by
      :class:`TaggedLineSegmentTagStart` / :class:`TaggedLineSegmentTagEnd`.
    * Unterminated tag blocks are auto-closed at :meth:`finish`.
    """

    def __init__(self, specs: list[TagSpec]) -> None:
        self.specs = specs
        self._line_buffer: str = ""
        self._active_tag: Any = None

    def parse(self, delta: str) -> list[TaggedLineSegment]:
        """Process a text delta and emit any newly-resolved segments.

        The delta is appended to the internal line buffer, then every complete
        line (up to and including ``\\n``) is classified.  If the remaining
        partial line can no longer become a tag line, it is emitted as well.

        Args:
            delta: Incoming text chunk (may contain zero or more newlines).

        Returns:
            List of segments produced by this delta.
        """
        cdef int newline_idx
        cdef str line
        cdef str buf
        cdef list segments

        self._line_buffer += delta
        segments = []
        buf = self._line_buffer

        # Drain complete lines.
        while True:
            newline_idx = buf.find("\n")
            if newline_idx == -1:
                break
            line = buf[: newline_idx + 1]
            buf = buf[newline_idx + 1 :]
            self._line_buffer = buf
            self._finish_line(line, segments)

        self._line_buffer = buf

        # If the remaining partial line can never become a tag line,
        # flush it immediately so it does not stall visible output.
        if buf and not self._is_tag_prefix(buf.strip()):
            self._push_text(buf, segments)
            self._line_buffer = ""

        return segments

    def finish(self) -> list[TaggedLineSegment]:
        """Flush any remaining buffered state.

        If the pending partial line exactly matches an ``open`` or ``close``
        delimiter, the appropriate boundary segment is emitted.  Otherwise the
        text is emitted as Normal or TagDelta (depending on whether a tag is
        currently open).  Finally, any still-open tag block is auto-closed with
        a :class:`TaggedLineSegmentTagEnd`.

        Returns:
            List of final segments.
        """
        cdef list segments
        cdef str slug
        cdef object open_spec
        cdef object close_spec

        segments = []

        if self._line_buffer:
            slug = self._line_buffer.strip()
            open_spec = self._match_open(slug)
            if open_spec is not None:
                segments.append(TaggedLineSegmentTagStart(open_spec.tag))
                self._active_tag = open_spec.tag
            else:
                close_spec = self._match_close(slug)
                if close_spec is not None:
                    segments.append(TaggedLineSegmentTagEnd(close_spec.tag))
                    self._active_tag = None
                else:
                    self._push_text(self._line_buffer, segments)
            self._line_buffer = ""

        if self._active_tag is not None:
            segments.append(TaggedLineSegmentTagEnd(self._active_tag))
            self._active_tag = None

        return segments

    def _push_text(self, text: str, segments: list[TaggedLineSegment]) -> None:
        """Emit ``text`` as the appropriate segment type, coalescing when possible.

        If a tag is currently active, ``text`` becomes a
        :class:`TaggedLineSegmentTagDelta`; otherwise it becomes a
        :class:`TaggedLineSegmentNormal`.  Consecutive segments of the same
        type (and same tag, for deltas) are merged into one segment so the
        output stays compact.
        """
        cdef object last
        cdef object active = self._active_tag

        if active is not None:
            if segments:
                last = segments[-1]
                if isinstance(last, TaggedLineSegmentTagDelta) and last.tag == active:
                    last.text += text
                    return
            segments.append(TaggedLineSegmentTagDelta(active, text))
        else:
            if segments:
                last = segments[-1]
                if isinstance(last, TaggedLineSegmentNormal):
                    last.text += text
                    return
            segments.append(TaggedLineSegmentNormal(text))

    def _finish_line(self, line: str, segments: list[TaggedLineSegment]) -> None:
        """Classify a complete line (including its trailing ``\\n``).

        The line is trimmed and checked against ``open`` / ``close``
        delimiters in order.  Tag lines are consumed entirely; non-tag lines
        are forwarded to :meth:`_push_text`.
        """
        cdef str slug
        cdef object open_spec
        cdef object close_spec

        slug = line.strip()
        open_spec = self._match_open(slug)
        if open_spec is not None:
            segments.append(TaggedLineSegmentTagStart(open_spec.tag))
            self._active_tag = open_spec.tag
            return

        close_spec = self._match_close(slug)
        if close_spec is not None:
            segments.append(TaggedLineSegmentTagEnd(close_spec.tag))
            self._active_tag = None
            return

        self._push_text(line, segments)

    def _is_tag_prefix(self, slug: str) -> bool:
        """Return ``True`` if ``slug`` is a prefix of any ``open`` or ``close``."""
        cdef object spec
        cdef str open_str
        cdef str close_str
        for spec in self.specs:
            open_str = spec.open
            close_str = spec.close
            if open_str.startswith(slug) or close_str.startswith(slug):
                return True
        return False

    def _match_open(self, slug: str) -> TagSpec | None:
        """Return the first spec whose ``open`` exactly equals ``slug``."""
        cdef object spec
        for spec in self.specs:
            if spec.open == slug:
                return spec
        return None

    def _match_close(self, slug: str) -> TagSpec | None:
        """Return the first spec whose ``close`` exactly equals ``slug``."""
        cdef object spec
        for spec in self.specs:
            if spec.close == slug:
                return spec
        return None
