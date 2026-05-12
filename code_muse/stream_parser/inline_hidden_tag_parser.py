"""Streaming parser for inline hidden tags.

Scans text for user-defined open/close delimiter pairs, extracts the content
between them as hidden payloads, and strips the delimiters from visible text.
Tags are matched literally and are not nested.

Partial delimiters that span chunk boundaries are buffered correctly using
suffix/prefix overlap checks so that a split ``<oai-mem-citation>`` is still
recognised when the chunks are ``'<oai-'`` and ``'mem-citation>'``.
"""

from dataclasses import dataclass
from typing import TypeVar

from code_muse.stream_parser.stream_text_chunk import StreamTextChunk
from code_muse.stream_parser.stream_text_parser import StreamTextParser

T = TypeVar("T")


@dataclass
class InlineTagSpec[T]:
    """Specification for a single hidden inline tag type.

    Attributes:
        tag: Payload type / identifier emitted in extracted results.
        open: Literal opening delimiter (e.g. ``"<oai-mem-citation>"``).
        close: Literal closing delimiter (e.g. ``"</oai-mem-citation>"``).
    """

    tag: T
    open: str
    close: str


@dataclass
class ExtractedInlineTag[T]:
    """Payload produced when an inline tag is fully closed.

    Attributes:
        tag: The tag identifier from the matching :class:`InlineTagSpec`.
        content: Text that appeared between the open and close delimiters.
    """

    tag: T
    content: str


def _longest_suffix_prefix_len(s: str, needle: str) -> int:
    """Return the largest ``k > 0`` such that ``s`` ends with ``needle[:k]``.

    This tells us how many characters at the end of ``s`` might be a partial
    occurrence of ``needle`` when more input arrives in the next chunk.

    Args:
        s: The string to inspect (usually the pending buffer).
        needle: The delimiter we are searching for.

    Returns:
        Length of the longest overlap, or ``0`` when there is none.
    """
    if not needle:
        return 0
    max_k = min(len(s), len(needle))
    for k in range(max_k, 0, -1):
        if s.endswith(needle[:k]):
            return k
    return 0


class InlineHiddenTagParser(StreamTextParser[T]):
    """Streaming parser that extracts hidden inline tags from text.

    * Searches for the earliest open delimiter; when two open delimiters start
      at the same position, the longer one wins (longest-match tiebreaker).
    * Once inside a tag, everything up to the matching close delimiter is
      treated as literal content—**nested tags are not parsed**.
    * On chunk boundaries, characters that could be a partial delimiter are
      kept in the pending buffer rather than being emitted as visible text.
    * Unterminated tags are auto-closed at :meth:`finish`; their buffered
      content becomes the extracted payload.
    """

    def __init__(self, specs: list[InlineTagSpec[T]]) -> None:
        if not specs:
            raise ValueError("InlineHiddenTagParser requires at least one tag spec")
        for spec in specs:
            if not spec.open:
                raise ValueError(
                    "InlineHiddenTagParser requires non-empty open delimiters"
                )
            if not spec.close:
                raise ValueError(
                    "InlineHiddenTagParser requires non-empty close delimiters"
                )
        self.specs = specs
        self._pending: str = ""
        self._active_spec: InlineTagSpec[T] | None = None
        self._active_content: str = ""

    def push_str(self, chunk: str) -> StreamTextChunk[T]:
        """Feed a new text chunk and scan for tag delimiters.

        The chunk is appended to any buffered pending text, then the parser
        loops until it can no longer make forward progress:

        1. If a tag is open, search for its close delimiter.
           * Found → emit the extracted tag and drain through the close.
           * Not found → keep a suffix that might be a partial close,
             drain the rest into the tag's content buffer.
        2. Otherwise, search for the next open delimiter.
           * Found → emit visible text before it, drain through the open,
             start tracking tag content.
           * Not found → keep a suffix that might be a partial open,
             drain the rest as visible text.

        Args:
            chunk: Incoming text delta.

        Returns:
            Visible text and any fully-closed tags found in this delta.
        """
        self._pending += chunk
        visible_parts: list[str] = []
        extracted_parts: list[ExtractedInlineTag[T]] = []

        while True:
            if self._active_spec is not None:
                close_pos = self._pending.find(self._active_spec.close)
                if close_pos != -1:
                    # Close delimiter found.
                    content = self._active_content + self._pending[:close_pos]
                    extracted_parts.append(
                        ExtractedInlineTag(self._active_spec.tag, content)
                    )
                    # Drain through the close delimiter.
                    close_len = len(self._active_spec.close)
                    self._pending = self._pending[close_pos + close_len :]
                    self._active_spec = None
                    self._active_content = ""
                    continue

                # No close yet — keep characters that could be a partial
                # close delimiter at the end of the buffer.
                keep = _longest_suffix_prefix_len(
                    self._pending, self._active_spec.close
                )
                drain_len = len(self._pending) - keep
                self._active_content += self._pending[:drain_len]
                self._pending = self._pending[drain_len:]
                break

            # No active tag — look for the next open delimiter.
            next_open = self._find_next_open()
            if next_open is not None:
                pos, spec_idx = next_open
                spec = self.specs[spec_idx]
                # Emit visible text before the open delimiter.
                visible_parts.append(self._pending[:pos])
                # Drain through the open delimiter.
                open_len = len(spec.open)
                self._pending = self._pending[pos + open_len :]
                self._active_spec = spec
                self._active_content = ""
                continue

            # No open delimiter found — keep characters that could be a
            # partial open delimiter at the end of the buffer.
            keep = self._max_open_prefix_suffix_len()
            drain_len = len(self._pending) - keep
            visible_parts.append(self._pending[:drain_len])
            self._pending = self._pending[drain_len:]
            break

        return StreamTextChunk(
            visible_text="".join(visible_parts),
            extracted=extracted_parts,
        )

    def finish(self) -> StreamTextChunk[T]:
        """Flush any remaining state.

        If a tag is still open, its accumulated content is emitted as an
        :class:`ExtractedInlineTag` with the tag's identifier.  Any leftover
        pending text (without an active tag) is emitted as visible text.

        Returns:
            Final visible text and any auto-closed extracted tags.
        """
        visible = ""
        extracted: list[ExtractedInlineTag[T]] = []

        if self._active_spec is not None:
            content = self._active_content + self._pending
            extracted.append(ExtractedInlineTag(self._active_spec.tag, content))
            self._active_spec = None
            self._active_content = ""
            self._pending = ""
        else:
            visible = self._pending
            self._pending = ""

        return StreamTextChunk(visible_text=visible, extracted=extracted)

    def _find_next_open(self) -> tuple[int, int] | None:
        """Find the earliest open delimiter in the pending buffer.

        Returns:
            ``(position, spec_index)`` of the earliest open delimiter, or
            ``None`` when no open delimiter is present.  Tie-breaking rules:

            1. Smallest position (earliest in the buffer).
            2. Longest open delimiter at that position.
            3. Lowest spec index (stable ordering).
        """
        candidates: list[tuple[int, int, int]] = []
        for i, spec in enumerate(self.specs):
            pos = self._pending.find(spec.open)
            if pos != -1:
                candidates.append((pos, len(spec.open), i))
        if not candidates:
            return None
        best = min(candidates, key=lambda c: (c[0], -c[1], c[2]))
        return best[0], best[2]

    def _max_open_prefix_suffix_len(self) -> int:
        """Maximum overlap between the end of ``pending`` and any open delimiter.

        Returns:
            Largest ``k > 0`` such that ``pending`` ends with the first ``k``
            characters of at least one open delimiter.
        """
        max_len = 0
        for spec in self.specs:
            max_len = max(max_len, _longest_suffix_prefix_len(self._pending, spec.open))
        return max_len
