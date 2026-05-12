from enum import Enum, auto

from code_muse.stream_parser import (
    TaggedLineParser,
    TaggedLineSegmentNormal,
    TaggedLineSegmentTagDelta,
    TaggedLineSegmentTagEnd,
    TaggedLineSegmentTagStart,
    TagSpec,
)


class Tag(Enum):
    Block = auto()


def test_buffers_prefix_until_tag_is_decided() -> None:
    parser = TaggedLineParser([TagSpec(open="<tag>", close="</tag>", tag=Tag.Block)])
    segments = parser.parse("<t")
    segments.extend(parser.parse("ag>\nline\n</tag>\n"))
    segments.extend(parser.finish())
    assert segments == [
        TaggedLineSegmentTagStart(Tag.Block),
        TaggedLineSegmentTagDelta(Tag.Block, "line\n"),
        TaggedLineSegmentTagEnd(Tag.Block),
    ]


def test_rejects_tag_lines_with_extra_text() -> None:
    parser = TaggedLineParser([TagSpec(open="<tag>", close="</tag>", tag=Tag.Block)])
    segments = parser.parse("<tag> extra\n")
    segments.extend(parser.finish())
    assert segments == [TaggedLineSegmentNormal("<tag> extra\n")]
