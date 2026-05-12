"""Tests for conversation_snapshots.py."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from code_muse.plugins.checkpointing.conversation_snapshots import (
    create_snapshot,
    list_snapshots,
    load_snapshot,
)


def test_create_snapshot_roundtrip(mock_project_root: Path) -> None:
    agent = MagicMock()
    agent.name = "test_agent"
    agent.model = "gpt-4"
    agent.get_message_history.return_value = [
        {"role": "system", "content": "hello"},
        {"role": "user", "content": "world"},
    ]

    with patch(
        "code_muse.plugins.checkpointing.conversation_snapshots.get_current_agent",
        return_value=agent,
    ):
        path = create_snapshot(agent, "write_file", "tc1")
        assert path is not None
        assert path.exists()

        data = load_snapshot(path)
        assert data is not None
        assert data["tool_name"] == "write_file"
        assert data["tool_call_id"] == "tc1"
        assert data["agent_state"]["name"] == "test_agent"
        assert len(data["messages"]) == 2


def test_load_snapshot_missing_keys(mock_project_root: Path) -> None:
    bad_path = mock_project_root / "bad.json"
    bad_path.write_text(json.dumps({"turn_id": "x"}), encoding="utf-8")
    assert load_snapshot(bad_path) is None


def test_load_snapshot_invalid_json(mock_project_root: Path) -> None:
    bad_path = mock_project_root / "bad.json"
    bad_path.write_text("not json", encoding="utf-8")
    assert load_snapshot(bad_path) is None


def test_list_snapshots_sorted(mock_project_root: Path) -> None:
    snapshot_dir = mock_project_root / "snapshots"
    snapshot_dir.mkdir(parents=True, exist_ok=True)

    for idx, ts in enumerate(
        ["2025-01-02T00:00:00+00:00", "2025-01-01T00:00:00+00:00"]
    ):
        path = snapshot_dir / f"snapshot_{ts.replace(':', '_')}.json"
        path.write_text(
            json.dumps(
                {
                    "turn_id": f"t{idx}",
                    "timestamp": ts,
                    "tool_name": "write_file",
                    "messages": [],
                    "agent_state": {},
                }
            ),
            encoding="utf-8",
        )

    results = list_snapshots(mock_project_root)
    assert len(results) == 2
    assert results[0]["timestamp"] == "2025-01-02T00:00:00+00:00"
    assert results[1]["timestamp"] == "2025-01-01T00:00:00+00:00"


def test_list_snapshots_empty(mock_project_root: Path) -> None:
    assert list_snapshots(mock_project_root) == []
