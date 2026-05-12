"""Tests for stub consolidation."""

from pathlib import Path

from code_muse.plugins.autonomous_memory.consolidation import (
    consolidate_memories,
    write_memory_files,
)
from code_muse.plugins.autonomous_memory.extraction import ExtractionResult


def test_consolidate_empty() -> None:
    """Empty extraction list produces a placeholder doc."""
    md = consolidate_memories([], Path("/tmp"))
    assert "No sessions extracted yet" in md


def test_consolidate_basic() -> None:
    """Extractions are concatenated with headers."""
    ex1 = ExtractionResult(
        session_path="/tmp/s1",
        raw_memory="## Session Summary\n- Messages: 2 user",
        synopsis="S1",
        extracted_at="2025-01-01T00:00:00+00:00",
    )
    ex2 = ExtractionResult(
        session_path="/tmp/s2",
        raw_memory="## Session Summary\n- Messages: 3 user",
        synopsis="S2",
        extracted_at="2025-01-02T00:00:00+00:00",
    )
    md = consolidate_memories([ex1, ex2], Path("/tmp"))
    assert "Generated from 2 sessions" in md
    assert "/tmp/s1" in md
    assert "/tmp/s2" in md
    assert "2 user" in md
    assert "3 user" in md


def test_consolidate_deduplicates() -> None:
    """Identical raw_memory blocks are deduplicated."""
    ex1 = ExtractionResult(
        session_path="/tmp/s1",
        raw_memory="same block",
        synopsis="S1",
        extracted_at="2025-01-01T00:00:00+00:00",
    )
    ex2 = ExtractionResult(
        session_path="/tmp/s2",
        raw_memory="same block",
        synopsis="S2",
        extracted_at="2025-01-02T00:00:00+00:00",
    )
    md = consolidate_memories([ex1, ex2], Path("/tmp"))
    assert md.count("same block") == 1


def test_write_memory_files(tmp_path: Path) -> None:
    """Both MEMORY.md and memory_summary.md are written."""
    consolidated = "# Project Memory\n\n" + ("word " * 600)
    memory_path, summary_path = write_memory_files(consolidated, tmp_path)

    assert memory_path == tmp_path / "MEMORY.md"
    assert summary_path == tmp_path / "memory_summary.md"
    assert memory_path.exists()
    assert summary_path.exists()
    assert (
        len(memory_path.read_text().split()) == 603
    )  # "# Project Memory" = 3 words + 600 words
    assert len(summary_path.read_text().split()) <= 505  # truncated ~500 words
