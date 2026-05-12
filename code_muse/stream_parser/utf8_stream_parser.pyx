# cython: language_level=3
"""UTF-8 byte-stream adapter that wraps a StreamTextParser.

Buffers partial code points across chunk boundaries and rolls back entire
chunks on invalid UTF-8 so the wrapped parser never sees malformed text.
"""

from typing import TypeVar

from code_muse.stream_parser.stream_text_chunk import StreamTextChunk
from code_muse.stream_parser.stream_text_parser import StreamTextParser

T = TypeVar("T")


class Utf8StreamParserError(Exception):
    """Base error for Utf8StreamParser."""

    pass


class InvalidUtf8(Utf8StreamParserError):
    """Raised when a pushed byte chunk contains an invalid UTF-8 sequence.

    The chunk is rolled back; the parser's pending buffer is restored to its
    state before the chunk was pushed.
    """

    def __init__(self, valid_up_to: int, error_len: int) -> None:
        self.valid_up_to = valid_up_to
        self.error_len = error_len
        super().__init__(
            f"invalid UTF-8 in streamed bytes at offset {valid_up_to} "
            f"(error length {error_len})"
        )


class IncompleteUtf8AtEof(Utf8StreamParserError):
    """Raised at finish() or into_inner() when an incomplete code point remains."""

    def __init__(self) -> None:
        super().__init__("incomplete UTF-8 code point at end of stream")


class Utf8StreamParser:
    """Wraps a StreamTextParser and accepts raw bytes.

    * Buffers incomplete UTF-8 code points across chunk boundaries.
    * On invalid UTF-8, rolls back the **entire** chunk and raises.
    * On incomplete-but-valid UTF-8, processes the valid prefix and keeps
      the incomplete tail buffered.
    * ``finish()`` flushes pending bytes; raises if a code point is incomplete.
    * ``into_inner()`` returns the wrapped parser only when no bytes are pending.
    * ``into_inner_lossy()`` returns the wrapped parser, dropping pending bytes.

    The wrapped parser never receives malformed text.
    """

    def __init__(self, inner: StreamTextParser[T]) -> None:
        self.inner = inner
        self._pending_utf8: bytearray = bytearray()

    def push_bytes(self, const unsigned char[:] chunk) -> StreamTextChunk[T]:
        """Feed a new byte chunk.

        Args:
            chunk: Raw bytes to decode and forward to the inner parser.

        Returns:
            Visible text and extracted payloads from the inner parser.

        Raises:
            InvalidUtf8: If the chunk (combined with any previously buffered
                partial code point) contains an invalid UTF-8 sequence. The
                entire chunk is rolled back so the buffer is restored to its
                pre-call state.
        """
        cdef int old_len
        cdef int valid_up_to
        cdef bint is_incomplete

        # Fast path: no pending bytes and chunk decodes cleanly.
        if not self._pending_utf8:
            try:
                text = bytes(chunk).decode("utf-8")
                return self.inner.push_str(text)
            except UnicodeDecodeError as err:
                is_incomplete = (
                    err.reason == "unexpected end of data" and err.end == len(chunk)
                )
                if not is_incomplete:
                    raise InvalidUtf8(err.start, err.end - err.start) from err
                # Buffer the chunk; valid prefix will be consumed below.
                self._pending_utf8.extend(chunk)
                valid_up_to = err.start
                if valid_up_to == 0:
                    return StreamTextChunk()
                text = bytes(chunk[:valid_up_to]).decode("utf-8")
                out = self.inner.push_str(text)
                del self._pending_utf8[:valid_up_to]
                return out

        # Slow path: append to existing pending buffer.
        old_len = len(self._pending_utf8)
        self._pending_utf8.extend(chunk)

        try:
            text = self._pending_utf8.decode("utf-8")
        except UnicodeDecodeError as err:
            # Distinguish "invalid byte sequence" from "incomplete at end".
            # In Python an incomplete sequence at the very end reports
            # ``reason == "unexpected end of data"`` and ``err.end`` equals
            # ``len(self._pending_utf8)``.  Anything else is an actual error.
            is_incomplete = err.reason == "unexpected end of data" and err.end == len(
                self._pending_utf8
            )

            if not is_incomplete:
                # Invalid sequence somewhere in the buffer.  Roll back the
                # entire chunk so the inner parser never sees malformed data.
                del self._pending_utf8[old_len:]
                raise InvalidUtf8(err.start, err.end - err.start) from err

            # Incomplete code point at the end of the buffer.
            valid_up_to = err.start
            if valid_up_to == 0:
                # Nothing valid to forward yet.
                return StreamTextChunk()

            # Process the valid prefix.  Defend against the edge case where
            # the prefix itself fails to decode (nested error).
            try:
                text = bytes(self._pending_utf8[:valid_up_to]).decode("utf-8")
            except UnicodeDecodeError as nested_err:
                del self._pending_utf8[old_len:]
                raise InvalidUtf8(
                    nested_err.start, nested_err.end - nested_err.start
                ) from nested_err

            out = self.inner.push_str(text)
            del self._pending_utf8[:valid_up_to]
            return out

        # Full buffer decoded cleanly.
        out = self.inner.push_str(text)
        self._pending_utf8.clear()
        return out

    def finish(self) -> StreamTextChunk[T]:
        """Flush any buffered bytes at end-of-stream.

        Returns:
            Any visible text and extracted payloads produced by the inner
            parser for the final pending bytes.

        Raises:
            IncompleteUtf8AtEof: If an incomplete UTF-8 code point remains
                in the buffer.  The bytes are **not** consumed; they stay
                buffered so the caller can decide what to do next.
        """
        if not self._pending_utf8:
            return self.inner.finish()

        # Attempt to decode whatever is left.  If it is incomplete, raise.
        try:
            text = self._pending_utf8.decode("utf-8")
        except UnicodeDecodeError as err:
            if err.reason == "unexpected end of data" and err.end == len(
                self._pending_utf8
            ):
                raise IncompleteUtf8AtEof() from err
            # Should be unreachable for a previously-validated buffer, but
            # treat it as invalid UTF-8.
            raise InvalidUtf8(err.start, err.end - err.start) from err

        out = self.inner.push_str(text)
        self._pending_utf8.clear()
        tail = self.inner.finish()
        return StreamTextChunk(
            visible_text=out.visible_text + tail.visible_text,
            extracted=out.extracted + tail.extracted,
        )

    def into_inner(self) -> StreamTextParser[T]:
        """Return the wrapped parser only if no bytes are pending.

        Returns:
            The inner StreamTextParser instance.

        Raises:
            IncompleteUtf8AtEof: If there are pending bytes (incomplete code
                point) in the buffer.
        """
        if self._pending_utf8:
            raise IncompleteUtf8AtEof()
        return self.inner

    def into_inner_lossy(self) -> StreamTextParser[T]:
        """Return the wrapped parser, discarding any pending bytes.

        Returns:
            The inner StreamTextParser instance.  Any incomplete UTF-8 code
            point buffered across previous chunks is silently dropped.
        """
        self._pending_utf8.clear()
        return self.inner
