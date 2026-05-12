"""Tests for the session scanner."""

import json
import time
from pathlib import Path

from code_muse.plugins.autonomous_memory.session_scanner import (
    get_memory_dir,
    get_project_hash,
    get_sessions_dir,
    mark_session_processed,
    scan_eligible_sessions,
)


def test_scan_missing_sessions_dir() -> None:
    """Missing sessions directory → empty list."""
    missing = Path("/nonexistent/sessions")
    state = Path("/nonexistent/state.json")
    assert scan_eligible_sessions(missing, state) == []


def test_scan_filters_messages_and_idle(tmp_path: Path) -> None:
    """Only sessions with >= 10 user messages and > 3h idle are returned."""
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    state_file = tmp_path / "state.json"

    # Session A: 12 user messages, old mtime
    s_a = sessions_dir / "session_a"
    s_a.mkdir()
    msgs_a = s_a / "messages.jsonl"
    msgs_a.write_text(
        "\n".join(
            [json.dumps({"role": "user", "content": f"msg {i}"}) for i in range(12)]
        )
    )
    # Force mtime to > 4 hours ago
    old_time = time.time() - 20_000
    msgs_a.touch()
    # utime may fail on some platforms with restricted paths, so guard it
    try:
        msgs_a.touch()
        import os

        os.utime(str(msgs_a), (old_time, old_time))
    except Exception:
        pass

    # Session B: 5 user messages (too few)
    s_b = sessions_dir / "session_b"
    s_b.mkdir()
    msgs_b = s_b / "messages.jsonl"
    msgs_b.write_text(
        "\n".join(
            [json.dumps({"role": "user", "content": f"msg {i}"}) for i in range(5)]
        )
    )
    try:
        import os

        os.utime(str(msgs_b), (old_time, old_time))
    except Exception:
        pass

    # Session C: active (lock file present)
    s_c = sessions_dir / "session_c"
    s_c.mkdir()
    msgs_c = s_c / "messages.jsonl"
    msgs_c.write_text(
        "\n".join(
            [json.dumps({"role": "user", "content": f"msg {i}"}) for i in range(15)]
        )
    )
    (s_c / ".session_lock").touch()

    results = scan_eligible_sessions(sessions_dir, state_file)
    names = {r.path.name for r in results}
    assert "session_a" in names
    assert "session_b" not in names
    assert "session_c" not in names


def test_scan_excludes_processed(tmp_path: Path) -> None:
    """Processed sessions are skipped."""
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    state_file = tmp_path / "state.json"

    s = sessions_dir / "session_old"
    s.mkdir()
    msgs = s / "messages.jsonl"
    msgs.write_text(
        "\n".join(
            [json.dumps({"role": "user", "content": f"msg {i}"}) for i in range(11)]
        )
    )
    old_time = time.time() - 20_000
    try:
        import os

        os.utime(str(msgs), (old_time, old_time))
    except Exception:
        pass

    mark_session_processed(state_file, str(s))
    results = scan_eligible_sessions(sessions_dir, state_file)
    assert all(str(r.path) != str(s) for r in results)


def test_scan_sorts_by_last_active_descending(tmp_path: Path) -> None:
    """Results are sorted most-recent first."""
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    state_file = tmp_path / "state.json"

    for idx, name in enumerate(("older", "newer")):
        s = sessions_dir / name
        s.mkdir()
        msgs = s / "messages.jsonl"
        msgs.write_text(
            "\n".join(
                [json.dumps({"role": "user", "content": f"msg {i}"}) for i in range(11)]
            )
        )
        # older = 10h ago, newer = 5h ago
        mtime = time.time() - (15_000 if idx == 0 else 20_000)
        try:
            import os

            os.utime(str(msgs), (mtime, mtime))
        except Exception:
            pass

    results = scan_eligible_sessions(sessions_dir, state_file)
    # Both should be eligible; order should be descending by mtime
    assert len(results) == 2
    assert results[0].last_active >= results[1].last_active


def test_get_sessions_dir() -> None:
    """get_sessions_dir returns the expected path."""
    path = get_sessions_dir()
    assert path.name == "sessions"
    assert path.parent.name == ".muse"


def test_get_memory_dir() -> None:
    """get_memory_dir returns a project-scoped path."""
    path = get_memory_dir("abc123")
    assert path.name == "abc123"
    assert path.parent.name == "memory"


def test_get_project_hash() -> None:
    """get_project_hash returns a 12-char hex string."""
    h = get_project_hash("/some/cwd")
    assert len(h) == 12
    assert h == get_project_hash("/some/cwd")
    assert h != get_project_hash("/other/cwd")
