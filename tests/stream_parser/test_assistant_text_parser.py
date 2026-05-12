from code_muse.stream_parser import (
    AssistantTextChunk,
    AssistantTextStreamParser,
    ProposedPlanSegment,
    ProposedPlanSegmentType,
)


def test_parses_citations_across_seed_and_delta_boundaries() -> None:
    parser = AssistantTextStreamParser(plan_mode=False)
    seeded = parser.push_str("hello <oai-mem-citation>doc")
    parsed = parser.push_str("1</oai-mem-citation> world")
    tail = parser.finish()

    assert seeded.visible_text == "hello "
    assert seeded.citations == []
    assert parsed.visible_text == " world"
    assert parsed.citations == ["doc1"]
    assert tail.visible_text == ""
    assert tail.citations == []


def test_parses_plan_segments_after_citation_stripping() -> None:
    parser = AssistantTextStreamParser(plan_mode=True)
    seeded = parser.push_str("Intro\n<proposed")
    parsed = parser.push_str(
        "_plan>\n- step <oai-mem-citation>doc</oai-mem-citation>\n"
    )
    tail = parser.push_str("</proposed_plan>\nOutro")
    finish = parser.finish()

    assert seeded.visible_text == "Intro\n"
    assert seeded.plan_segments == [
        ProposedPlanSegment(ProposedPlanSegmentType.NORMAL, "Intro\n")
    ]
    assert parsed.visible_text == ""
    assert parsed.citations == ["doc"]
    assert parsed.plan_segments == [
        ProposedPlanSegment(ProposedPlanSegmentType.PLAN_START),
        ProposedPlanSegment(ProposedPlanSegmentType.PLAN_DELTA, "- step \n"),
    ]
    assert tail.visible_text == "Outro"
    assert tail.plan_segments == [
        ProposedPlanSegment(ProposedPlanSegmentType.PLAN_END),
        ProposedPlanSegment(ProposedPlanSegmentType.NORMAL, "Outro"),
    ]
    assert finish.is_empty()


def test_assistant_parser_non_plan_mode_ignores_plan_tags() -> None:
    parser = AssistantTextStreamParser(plan_mode=False)
    chunk = parser.push_str("text<proposed_plan>\nplan\n</proposed_plan>more")
    tail = parser.finish()
    assert chunk.visible_text == "text<proposed_plan>\nplan\n</proposed_plan>more"
    assert chunk.plan_segments == []
    assert tail.is_empty()


def test_assistant_text_chunk_is_empty() -> None:
    chunk = AssistantTextChunk()
    assert chunk.is_empty()

    assert not AssistantTextChunk(visible_text="x").is_empty()
    assert not AssistantTextChunk(citations=["x"]).is_empty()
    assert not AssistantTextChunk(
        plan_segments=[ProposedPlanSegment(ProposedPlanSegmentType.PLAN_START)]
    ).is_empty()
