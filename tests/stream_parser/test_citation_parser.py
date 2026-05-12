from code_muse.stream_parser import (
    CitationStreamParser,
    StreamTextChunk,
    strip_citations,
)


def _collect_chunks(
    parser: CitationStreamParser, chunks: list[str]
) -> StreamTextChunk[str]:
    all_chunk = StreamTextChunk[str]()
    for chunk in chunks:
        nxt = parser.push_str(chunk)
        all_chunk.visible_text += nxt.visible_text
        all_chunk.extracted.extend(nxt.extracted)
    tail = parser.finish()
    all_chunk.visible_text += tail.visible_text
    all_chunk.extracted.extend(tail.extracted)
    return all_chunk


def test_citation_parser_streams_across_chunk_boundaries() -> None:
    parser = CitationStreamParser()
    out = _collect_chunks(
        parser,
        [
            "Hello <oai-mem-",
            "citation>source A</oai-mem-",
            "citation> world",
        ],
    )
    assert out.visible_text == "Hello  world"
    assert out.extracted == ["source A"]


def test_citation_parser_buffers_partial_open_tag_prefix() -> None:
    parser = CitationStreamParser()
    first = parser.push_str("abc <oai-mem-")
    assert first.visible_text == "abc "
    assert first.extracted == []

    second = parser.push_str("citation>x</oai-mem-citation>z")
    tail = parser.finish()
    assert second.visible_text == "z"
    assert second.extracted == ["x"]
    assert tail.is_empty()


def test_citation_parser_auto_closes_unterminated_tag_on_finish() -> None:
    parser = CitationStreamParser()
    out = _collect_chunks(parser, ["x<oai-mem-citation>source"])
    assert out.visible_text == "x"
    assert out.extracted == ["source"]


def test_citation_parser_preserves_partial_open_tag_at_eof_if_not_a_full_tag() -> None:
    parser = CitationStreamParser()
    out = _collect_chunks(parser, ["hello <oai-mem-"])
    assert out.visible_text == "hello <oai-mem-"
    assert out.extracted == []


def test_strip_citations_collects_all_citations() -> None:
    visible, citations = strip_citations(
        "a<oai-mem-citation>one</oai-mem-citation>b<oai-mem-citation>two</oai-mem-citation>c"
    )
    assert visible == "abc"
    assert citations == ["one", "two"]


def test_strip_citations_auto_closes_unterminated_citation_at_eof() -> None:
    visible, citations = strip_citations("x<oai-mem-citation>y")
    assert visible == "x"
    assert citations == ["y"]


def test_citation_parser_does_not_support_nested_tags() -> None:
    visible, citations = strip_citations(
        "a<oai-mem-citation>x<oai-mem-citation>y</oai-mem-citation>z</oai-mem-citation>b"
    )
    assert visible == "az</oai-mem-citation>b"
    assert citations == ["x<oai-mem-citation>y"]
