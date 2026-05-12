from code_muse.stream_parser import (
    ProposedPlanParser,
    ProposedPlanSegment,
    ProposedPlanSegmentType,
    StreamTextChunk,
    extract_proposed_plan_text,
    strip_proposed_plan_blocks,
)


def _collect_chunks(
    parser: ProposedPlanParser, chunks: list[str]
) -> StreamTextChunk[ProposedPlanSegment]:
    all_chunk = StreamTextChunk[ProposedPlanSegment]()
    for chunk in chunks:
        nxt = parser.push_str(chunk)
        all_chunk.visible_text += nxt.visible_text
        all_chunk.extracted.extend(nxt.extracted)
    tail = parser.finish()
    all_chunk.visible_text += tail.visible_text
    all_chunk.extracted.extend(tail.extracted)
    return all_chunk


def test_streams_proposed_plan_segments_and_visible_text() -> None:
    parser = ProposedPlanParser()
    out = _collect_chunks(
        parser,
        [
            "Intro text\n<prop",
            "osed_plan>\n- step 1\n",
            "</proposed_plan>\nOutro",
        ],
    )
    assert out.visible_text == "Intro text\nOutro"
    assert out.extracted == [
        ProposedPlanSegment(ProposedPlanSegmentType.NORMAL, "Intro text\n"),
        ProposedPlanSegment(ProposedPlanSegmentType.PLAN_START),
        ProposedPlanSegment(ProposedPlanSegmentType.PLAN_DELTA, "- step 1\n"),
        ProposedPlanSegment(ProposedPlanSegmentType.PLAN_END),
        ProposedPlanSegment(ProposedPlanSegmentType.NORMAL, "Outro"),
    ]


def test_preserves_non_tag_lines() -> None:
    parser = ProposedPlanParser()
    out = _collect_chunks(parser, ["  <proposed_plan> extra\n"])
    assert out.visible_text == "  <proposed_plan> extra\n"
    assert out.extracted == [
        ProposedPlanSegment(ProposedPlanSegmentType.NORMAL, "  <proposed_plan> extra\n")
    ]


def test_closes_unterminated_plan_block_on_finish() -> None:
    parser = ProposedPlanParser()
    out = _collect_chunks(parser, ["<proposed_plan>\n- step 1\n"])
    assert out.visible_text == ""
    assert out.extracted == [
        ProposedPlanSegment(ProposedPlanSegmentType.PLAN_START),
        ProposedPlanSegment(ProposedPlanSegmentType.PLAN_DELTA, "- step 1\n"),
        ProposedPlanSegment(ProposedPlanSegmentType.PLAN_END),
    ]


def test_strips_proposed_plan_blocks_from_text() -> None:
    text = "before\n<proposed_plan>\n- step\n</proposed_plan>\nafter"
    assert strip_proposed_plan_blocks(text) == "before\nafter"


def test_extracts_proposed_plan_text() -> None:
    text = "before\n<proposed_plan>\n- step\n</proposed_plan>\nafter"
    assert extract_proposed_plan_text(text) == "- step\n"
