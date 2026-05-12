import pytest

from code_muse.stream_parser import (
    CitationStreamParser,
    IncompleteUtf8AtEof,
    InvalidUtf8,
    StreamTextChunk,
    Utf8StreamParser,
)


def _collect_bytes(
    parser: Utf8StreamParser[CitationStreamParser], chunks: list[bytes]
) -> StreamTextChunk[str]:
    all_chunk = StreamTextChunk[str]()
    for chunk in chunks:
        nxt = parser.push_bytes(chunk)
        all_chunk.visible_text += nxt.visible_text
        all_chunk.extracted.extend(nxt.extracted)
    tail = parser.finish()
    all_chunk.visible_text += tail.visible_text
    all_chunk.extracted.extend(tail.extracted)
    return all_chunk


def test_utf8_stream_parser_handles_split_code_points_across_chunks() -> None:
    chunks = [b"A\xc3", b"\xa9<oai-mem-citation>\xe4", b"\xb8\xad</oai-mem-citation>Z"]
    parser = Utf8StreamParser(CitationStreamParser())
    out = _collect_bytes(parser, chunks)
    assert out.visible_text == "AéZ"
    assert out.extracted == ["中"]


def test_utf8_stream_parser_rolls_back_on_invalid_utf8_chunk() -> None:
    parser = Utf8StreamParser(CitationStreamParser())
    first = parser.push_bytes(bytes([0xC3]))
    assert first.is_empty()

    with pytest.raises(InvalidUtf8) as exc_info:
        parser.push_bytes(bytes([0x28]))
    assert exc_info.value.valid_up_to == 0
    assert exc_info.value.error_len == 1

    second = parser.push_bytes(bytes([0xA9, ord("x")]))
    tail = parser.finish()
    assert second.visible_text == "éx"
    assert not second.extracted
    assert tail.is_empty()


def test_utf8_stream_parser_rolls_back_entire_chunk_when_invalid_byte_follows_valid_prefix() -> (
    None
):
    parser = Utf8StreamParser(CitationStreamParser())
    with pytest.raises(InvalidUtf8) as exc_info:
        parser.push_bytes(b"ok\xff")
    assert exc_info.value.valid_up_to == 2
    assert exc_info.value.error_len == 1

    nxt = parser.push_bytes(b"!")
    assert nxt.visible_text == "!"
    assert not nxt.extracted


def test_utf8_stream_parser_errors_on_incomplete_code_point_at_eof() -> None:
    parser = Utf8StreamParser(CitationStreamParser())
    out = parser.push_bytes(bytes([0xE2, 0x82]))
    assert out.is_empty()

    with pytest.raises(IncompleteUtf8AtEof):
        parser.finish()


def test_utf8_stream_parser_into_inner_errors_when_partial_code_point_is_buffered() -> (
    None
):
    parser = Utf8StreamParser(CitationStreamParser())
    out = parser.push_bytes(bytes([0xC3]))
    assert out.is_empty()

    with pytest.raises(IncompleteUtf8AtEof):
        parser.into_inner()


def test_utf8_stream_parser_into_inner_lossy_drops_buffered_partial_code_point() -> (
    None
):
    parser = Utf8StreamParser(CitationStreamParser())
    out = parser.push_bytes(bytes([0xC3]))
    assert out.is_empty()

    inner = parser.into_inner_lossy()
    tail = inner.finish()
    assert tail.is_empty()
