"""Tests for the Upgrade Metrics event system (emit_metric, JSONL, buffer)."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from code_muse.plugins.upgrade_metrics.register_callbacks import (
    _MAX_BUFFER_SIZE,
    _ROTATION_SIZE_BYTES,
    _event_buffer,
    _reset_events,
    _reset_ledger,
    emit_metric,
)


@pytest.fixture(autouse=True)
def _reset():
    """Ensure clean state before and after every test."""
    _reset_ledger()
    _reset_events()
    # Re-enable if previously disabled
    import code_muse.plugins.upgrade_metrics.register_callbacks as _mod

    _mod._enabled = True
    yield
    _reset_ledger()
    _reset_events()
    _mod._enabled = True


@pytest.fixture
def jsonl_dir(tmp_path: Path) -> Path:
    """Redirect JSONL writes to a temp directory."""
    metrics_dir = tmp_path / "metrics"
    with patch(
        "code_muse.plugins.upgrade_metrics.register_callbacks._metrics_dir",
        return_value=metrics_dir,
    ):
        yield metrics_dir


# ---------------------------------------------------------------------------
# emit_metric records event in buffer
# ---------------------------------------------------------------------------


class TestEmitMetricRecordsEvent:
    def test_event_appears_in_buffer(self):
        emit_metric(
            "compression_applied",
            {"original_tokens": 5000, "compressed_tokens": 3000},
        )
        assert len(_event_buffer) == 1
        entry = _event_buffer[0]
        assert entry["event"] == "compression_applied"
        assert entry["data"]["original_tokens"] == 5000
        assert entry["data"]["compressed_tokens"] == 3000

    def test_event_has_timestamp(self):
        emit_metric("context_pruned", {"messages_pruned": 5})
        entry = _event_buffer[0]
        assert "timestamp" in entry
        assert isinstance(entry["timestamp"], float)

    def test_auto_computes_tokens_saved(self):
        emit_metric(
            "compression_applied",
            {"original_tokens": 5000, "compressed_tokens": 3000},
        )
        assert _event_buffer[0]["data"]["tokens_saved"] == 2000

    def test_no_auto_compute_without_both_keys(self):
        emit_metric("compression_applied", {"original_tokens": 5000})
        assert "tokens_saved" not in _event_buffer[0]["data"]

    def test_data_defaults_to_empty_dict(self):
        emit_metric("task_archived")
        assert _event_buffer[0]["data"] == {}


# ---------------------------------------------------------------------------
# tokens_saved auto-compute edge cases
# ---------------------------------------------------------------------------


class TestTokensSavedAutoCompute:
    def test_pre_set_tokens_saved_not_overwritten(self):
        """If caller provides tokens_saved, auto-compute does not overwrite."""
        emit_metric(
            "compression_applied",
            {
                "original_tokens": 5000,
                "compressed_tokens": 3000,
                "tokens_saved": 999,  # explicit value
            },
        )
        assert _event_buffer[0]["data"]["tokens_saved"] == 999

    def test_negative_savings_clamped_to_zero(self):
        """tokens_saved is clamped to 0 if compressed > original."""
        emit_metric(
            "compression_applied",
            {"original_tokens": 100, "compressed_tokens": 200},
        )
        assert _event_buffer[0]["data"]["tokens_saved"] == 0


# ---------------------------------------------------------------------------
# emit_metric validation
# ---------------------------------------------------------------------------


class TestEmitMetricValidation:
    def test_none_event_name_ignored(self):
        emit_metric(None, {"test": True})
        assert len(_event_buffer) == 0

    def test_empty_event_name_ignored(self):
        emit_metric("", {"test": True})
        assert len(_event_buffer) == 0


# ---------------------------------------------------------------------------
# emit_metric writes JSONL
# ---------------------------------------------------------------------------


class TestEmitMetricWritesJsonl:
    def test_event_written_to_file(self, jsonl_dir: Path):
        emit_metric("review_verdict", {"verdict": "approve"})
        path = jsonl_dir / "events.jsonl"
        assert path.exists()
        lines = path.read_text().strip().splitlines()
        assert len(lines) == 1
        entry = json.loads(lines[0])
        assert entry["event"] == "review_verdict"
        assert entry["data"]["verdict"] == "approve"

    def test_multiple_events(self, jsonl_dir: Path):
        emit_metric(
            "compression_applied",
            {"original_tokens": 1000, "compressed_tokens": 800},
        )
        emit_metric("context_pruned", {"messages_pruned": 3})
        path = jsonl_dir / "events.jsonl"
        lines = path.read_text().strip().splitlines()
        assert len(lines) == 2


# ---------------------------------------------------------------------------
# Event buffer capped at 500
# ---------------------------------------------------------------------------


class TestEventBufferCap:
    def test_buffer_capped_at_max(self):
        for i in range(_MAX_BUFFER_SIZE + 1):
            emit_metric("test_event", {"i": i})
        assert len(_event_buffer) == _MAX_BUFFER_SIZE
        # Oldest event (i=0) should be dropped
        assert _event_buffer[0]["data"]["i"] == 1

    def test_buffer_under_cap(self):
        for i in range(10):
            emit_metric("test_event", {"i": i})
        assert len(_event_buffer) == 10


# ---------------------------------------------------------------------------
# Standard events
# ---------------------------------------------------------------------------


class TestStandardEvents:
    @pytest.mark.parametrize(
        "event_name",
        [
            "compression_applied",
            "context_pruned",
            "review_verdict",
            "task_archived",
        ],
    )
    def test_core_event_type(self, event_name: str):
        emit_metric(event_name, {"test": True})
        assert _event_buffer[0]["event"] == event_name


# ---------------------------------------------------------------------------
# emit_metric when disabled
# ---------------------------------------------------------------------------


class TestEmitMetricWhenDisabled:
    def test_no_event_recorded_when_disabled(self):
        import code_muse.plugins.upgrade_metrics.register_callbacks as _mod

        _mod._enabled = False
        emit_metric("compression_applied", {"original_tokens": 5000})
        assert len(_event_buffer) == 0

    def test_no_jsonl_written_when_disabled(self, jsonl_dir: Path):
        import code_muse.plugins.upgrade_metrics.register_callbacks as _mod

        _mod._enabled = False
        emit_metric("compression_applied", {"original_tokens": 5000})
        path = jsonl_dir / "events.jsonl"
        assert not path.exists()


# ---------------------------------------------------------------------------
# JSONL rotation
# ---------------------------------------------------------------------------


class TestJsonlRotation:
    def test_file_rotates_when_exceeds_limit(self, jsonl_dir: Path):
        path = jsonl_dir / "events.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)

        # Write a file that exceeds the rotation limit
        with open(path, "w", encoding="utf-8") as f:
            # Each line is ~100 bytes, write enough to exceed 5MB
            big_line = json.dumps({"event": "padding", "data": {"x": "x" * 80}}) + "\n"
            target_lines = (_ROTATION_SIZE_BYTES // len(big_line.encode())) + 10
            for _ in range(target_lines):
                f.write(big_line)

        # Emitting a new event should trigger rotation
        emit_metric("after_rotation", {"test": True})

        # The .1 file should exist (the rotated original)
        rotated = path.with_suffix(".jsonl.1")
        assert rotated.exists()

        # The new file should have the latest event
        lines = path.read_text().strip().splitlines()
        assert len(lines) >= 1
        last = json.loads(lines[-1])
        assert last["event"] == "after_rotation"
