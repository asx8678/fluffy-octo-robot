from enum import Enum, auto

import pytest

from code_muse.stream_parser import (
    ExtractedInlineTag,
    InlineHiddenTagParser,
    InlineTagSpec,
    StreamTextChunk,
)


class Tag(Enum):
    A = auto()
    B = auto()


def _collect_chunks(
    parser: InlineHiddenTagParser[Tag], chunks: list[str]
) -> StreamTextChunk[ExtractedInlineTag[Tag]]:
    all_chunk = StreamTextChunk[ExtractedInlineTag[Tag]]()
    for chunk in chunks:
        nxt = parser.push_str(chunk)
        all_chunk.visible_text += nxt.visible_text
        all_chunk.extracted.extend(nxt.extracted)
    tail = parser.finish()
    all_chunk.visible_text += tail.visible_text
    all_chunk.extracted.extend(tail.extracted)
    return all_chunk


def test_generic_inline_parser_supports_multiple_tag_types() -> None:
    parser = InlineHiddenTagParser(
        [
            InlineTagSpec(Tag.A, "<a>", "</a>"),
            InlineTagSpec(Tag.B, "<b>", "</b>"),
        ]
    )
    out = _collect_chunks(parser, ["1<a>x</a>2<b>y</b>3"])
    assert out.visible_text == "123"
    assert len(out.extracted) == 2
    assert out.extracted[0] == ExtractedInlineTag(Tag.A, "x")
    assert out.extracted[1] == ExtractedInlineTag(Tag.B, "y")


def test_generic_inline_parser_supports_non_ascii_tag_delimiters() -> None:
    parser = InlineHiddenTagParser([InlineTagSpec(Tag.A, "<é>", "</é>")])
    out = _collect_chunks(parser, ["a<", "é>中</", "é>b"])
    assert out.visible_text == "ab"
    assert len(out.extracted) == 1
    assert out.extracted[0] == ExtractedInlineTag(Tag.A, "中")


def test_generic_inline_parser_prefers_longest_opener_at_same_offset() -> None:
    parser = InlineHiddenTagParser(
        [
            InlineTagSpec(Tag.A, "<a>", "</a>"),
            InlineTagSpec(Tag.B, "<ab>", "</ab>"),
        ]
    )
    out = _collect_chunks(parser, ["x<ab>y</ab>z"])
    assert out.visible_text == "xz"
    assert len(out.extracted) == 1
    assert out.extracted[0] == ExtractedInlineTag(Tag.B, "y")


def test_generic_inline_parser_rejects_empty_open_delimiter() -> None:
    with pytest.raises((AssertionError, ValueError)):
        InlineHiddenTagParser([InlineTagSpec(Tag.A, "", "</a>")])


def test_generic_inline_parser_rejects_empty_close_delimiter() -> None:
    with pytest.raises((AssertionError, ValueError)):
        InlineHiddenTagParser([InlineTagSpec(Tag.A, "<a>", "")])


def test_inline_parser_handles_nested_tags_of_different_types() -> None:
    parser = InlineHiddenTagParser(
        [
            InlineTagSpec(Tag.A, "<a>", "</a>"),
            InlineTagSpec(Tag.B, "<b>", "</b>"),
        ]
    )
    out = _collect_chunks(parser, ["<a><b>inner</b></a>"])
    assert out.visible_text == ""
    assert out.extracted == [ExtractedInlineTag(Tag.A, "<b>inner</b>")]
