"""Tests for memory injection."""

import time
from pathlib import Path

from code_muse.plugins.autonomous_memory.memory_injection import (
    inject_into_system_prompt,
    load_memory_injection,
)


def test_load_fresh_memory(tmp_path: Path, monkeypatch) -> None:
    """Fresh summary file is returned."""
    memory_dir = tmp_path / "memory" / "abc123"
    memory_dir.mkdir(parents=True)
    summary = memory_dir / "memory_summary.md"
    summary.write_text("Project knows about dogs.")

    monkeypatch.setattr(
        "code_muse.plugins.autonomous_memory.memory_injection.get_memory_dir",
        lambda _ph: memory_dir,
    )
    monkeypatch.setattr(
        "code_muse.plugins.autonomous_memory.memory_injection.get_project_hash",
        lambda _cwd=None: "abc123",
    )

    result = load_memory_injection(str(tmp_path))
    assert result == "Project knows about dogs."


def test_load_stale_memory(tmp_path: Path, monkeypatch) -> None:
    """Stale summary file (> 7 days) returns None."""
    memory_dir = tmp_path / "memory" / "abc123"
    memory_dir.mkdir(parents=True)
    summary = memory_dir / "memory_summary.md"
    summary.write_text("Old knowledge.")
    # Set mtime to 10 days ago
    old = time.time() - (10 * 86_400)
    summary.touch()
    import os

    os.utime(str(summary), (old, old))

    monkeypatch.setattr(
        "code_muse.plugins.autonomous_memory.memory_injection.get_memory_dir",
        lambda _ph: memory_dir,
    )
    monkeypatch.setattr(
        "code_muse.plugins.autonomous_memory.memory_injection.get_project_hash",
        lambda _cwd=None: "abc123",
    )

    result = load_memory_injection(str(tmp_path))
    assert result is None


def test_load_missing_memory(tmp_path: Path, monkeypatch) -> None:
    """Missing summary returns None without raising."""
    memory_dir = tmp_path / "memory" / "abc123"
    memory_dir.mkdir(parents=True)

    monkeypatch.setattr(
        "code_muse.plugins.autonomous_memory.memory_injection.get_memory_dir",
        lambda _ph: memory_dir,
    )
    monkeypatch.setattr(
        "code_muse.plugins.autonomous_memory.memory_injection.get_project_hash",
        lambda _cwd=None: "abc123",
    )

    result = load_memory_injection(str(tmp_path))
    assert result is None


def test_inject_into_system_prompt() -> None:
    """Memory section is appended to base prompt."""
    base = "You are a helpful assistant."
    memory = "- Dogs are great."
    combined = inject_into_system_prompt(base, memory)
    assert combined.startswith(base)
    assert "Memory Guidance" in combined
    assert "- Dogs are great." in combined
