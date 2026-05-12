"""Tests for BM25 relevance scorer."""

import pytest
from code_muse.plugins.autonomous_memory.bm25_scorer import (
    BM25Scorer,
    score_chunks_against_context,
    select_top_chunks,
)


class TestBM25Scorer:
    def test_basic_scoring(self) -> None:
        scorer = BM25Scorer()
        docs = [
            "the cat sat on the mat",
            "dogs are running in the park",
            "python is a programming language",
        ]
        scorer.fit(docs)
        score = scorer.score("cat mat", docs[0])
        assert score > 0

    def test_relevant_scores_higher(self) -> None:
        scorer = BM25Scorer()
        docs = [
            "python async await coroutine",
            "cats and dogs playing",
            "the weather is nice today",
        ]
        scorer.fit(docs)
        score_relevant = scorer.score("python programming async", docs[0])
        score_irrelevant = scorer.score("python programming async", docs[2])
        assert score_relevant > score_irrelevant

    def test_tokenization(self) -> None:
        tokens = BM25Scorer._tokenize("Hello, World! Python 3.11 async/await")
        # Should produce lowercase tokens >= 2 chars
        assert "hello" in tokens
        assert "world" in tokens
        assert "python" in tokens
        assert "async" in tokens
        assert "await" in tokens
        # Punctuation-only tokens excluded
        assert "," not in tokens

    def test_select_top_chunks_by_threshold(self) -> None:
        chunks = ["a", "b", "c", "d", "e"]
        scores = [0.5, 0.1, 0.8, 0.2, 0.9]
        result = select_top_chunks(chunks, scores, threshold=0.4)
        assert len(result) >= 1
        assert "b" not in result  # score 0.1 < 0.4

    def test_select_top_chunks_by_top_n(self) -> None:
        chunks = ["a", "b", "c", "d", "e"]
        scores = [0.5, 0.1, 0.8, 0.2, 0.9]
        result = select_top_chunks(chunks, scores, top_n=3)
        assert len(result) <= 3

    def test_min_keep_ensured(self) -> None:
        chunks = ["a", "b", "c"]
        scores = [0.1, 0.1, 0.1]
        result = select_top_chunks(chunks, scores, threshold=0.9, min_keep=2)
        assert len(result) == 2

    def test_empty_chunks(self) -> None:
        assert select_top_chunks([], [], threshold=0.5) == []

    def test_convenience_function(self) -> None:
        chunks = ["python code here", "irrelevant noise", "more python stuff"]
        context = "python programming"
        scores = score_chunks_against_context(chunks, context)
        assert scores[0] > scores[1]  # python-related scores higher

    def test_unfitted_scorer_raises(self) -> None:
        scorer = BM25Scorer()
        with pytest.raises(RuntimeError, match="Scorer not fitted"):
            scorer.score("query", "document")

    def test_error_chunks_score_high(self) -> None:
        """Chunks with error/exception keywords should score high against context with those terms."""
        chunks = [
            "running tests now",
            "Traceback: ValueError in module x",
            "all good here",
        ]
        context = "error exception traceback fix bug"
        scores = score_chunks_against_context(chunks, context)
        assert scores[1] > scores[0]  # error chunk > test chunk
        assert scores[1] > scores[2]  # error chunk > good chunk

    def test_project_name_scores_higher(self) -> None:
        """Chunk containing project name should score higher than generic text."""
        chunks = [
            "hello world example",
            "working on muse codebase",
            "general discussion",
        ]
        context = "muse project code"
        scores = score_chunks_against_context(chunks, context)
        assert scores[1] > scores[0]
        assert scores[1] > scores[2]
