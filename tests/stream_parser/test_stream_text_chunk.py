from code_muse.stream_parser import StreamTextChunk


def test_default_constructor_creates_empty_chunk() -> None:
    chunk = StreamTextChunk()
    assert chunk.visible_text == ""
    assert chunk.extracted == []
    assert chunk.is_empty()


def test_is_empty_returns_true_for_default_false_when_populated() -> None:
    chunk = StreamTextChunk()
    assert chunk.is_empty()

    chunk.visible_text = "hello"
    assert not chunk.is_empty()

    chunk2 = StreamTextChunk(extracted=["x"])
    assert not chunk2.is_empty()


def test_generic_type_parameter_works() -> None:
    chunk_str = StreamTextChunk[str]()
    assert chunk_str.extracted == []
    chunk_int = StreamTextChunk[int]()
    assert chunk_int.extracted == []
