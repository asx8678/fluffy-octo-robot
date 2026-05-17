"""Tests for the Trace Collector plugin (z30.4).

Covers TraceContext propagation, span writing/loading, tree building,
and /trace commands.
"""

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from code_muse.plugins.trace_collector import (
    TraceContext,
    clear_current_trace_context,
    get_current_trace_context,
    set_current_trace_context,
)
from code_muse.plugins.trace_collector.store import build_tree, load_trace, write_span

# ---------------------------------------------------------------------------
# TraceContext
# ---------------------------------------------------------------------------


class TestTraceContext:
    def test_default_context(self):
        ctx = TraceContext()
        assert ctx.trace_id
        assert ctx.current_span_id
        assert ctx.parent_span_id is None
        assert ctx.turn == 0
        assert ctx.agent_name == "muse"

    def test_child_span(self):
        parent = TraceContext(agent_name="muse")
        child = parent.child("retriever")
        assert child.trace_id == parent.trace_id
        assert child.parent_span_id == parent.current_span_id
        assert child.agent_name == "retriever"
        assert child.turn == 0
        assert child.current_span_id != parent.current_span_id

    def test_next_turn(self):
        ctx = TraceContext(agent_name="muse")
        ctx2 = ctx.next_turn()
        assert ctx2.trace_id == ctx.trace_id
        assert ctx2.current_span_id == ctx.current_span_id
        assert ctx2.turn == 1

    def test_frozen(self):
        ctx = TraceContext(agent_name="muse")
        with pytest.raises(AttributeError):
            ctx.agent_name = "other"  # type: ignore[misc]

    def test_swarm_id(self):
        ctx = TraceContext(agent_name="muse", swarm_id="swarm-abc")
        assert ctx.swarm_id == "swarm-abc"

    def test_as_dict(self):
        ctx = TraceContext(agent_name="muse", swarm_id="sw-1")
        d = ctx.as_dict()
        assert d["agent_name"] == "muse"
        assert d["swarm_id"] == "sw-1"
        assert "trace_id" in d


# ---------------------------------------------------------------------------
# ContextVar propagation
# ---------------------------------------------------------------------------


class TestContextVarPropagation:
    def setup_method(self):
        clear_current_trace_context()

    def test_get_returns_none_initially(self):
        assert get_current_trace_context() is None

    def test_set_and_get(self):
        ctx = TraceContext(agent_name="muse")
        set_current_trace_context(ctx)
        assert get_current_trace_context() is ctx

    def test_clear(self):
        ctx = TraceContext(agent_name="muse")
        set_current_trace_context(ctx)
        clear_current_trace_context()
        assert get_current_trace_context() is None

    def test_child_propagation(self):
        parent = TraceContext(agent_name="muse")
        set_current_trace_context(parent)
        child = parent.child("retriever")
        set_current_trace_context(child)
        current = get_current_trace_context()
        assert current is child
        assert current.parent_span_id == parent.current_span_id


# ---------------------------------------------------------------------------
# Trace store
# ---------------------------------------------------------------------------


class TestTraceStore:
    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()

    def test_write_and_load_span(self):
        trace_id = "test-trace-001"
        with patch(
            "code_muse.plugins.trace_collector.store._traces_dir",
            return_value=Path(self.tmpdir),
        ):
            write_span(
                trace_id=trace_id,
                span_id="span-1",
                parent_span_id=None,
                agent_name="muse",
                event_type="span_start",
                data={"model": "claude-4"},
            )
            spans = load_trace(trace_id)
        assert len(spans) == 1
        assert spans[0]["event_type"] == "span_start"
        assert spans[0]["agent_name"] == "muse"
        assert spans[0]["model"] == "claude-4"

    def test_load_nonexistent_trace(self):
        with patch(
            "code_muse.plugins.trace_collector.store._traces_dir",
            return_value=Path(self.tmpdir),
        ):
            spans = load_trace("nonexistent")
        assert spans == []

    def test_multiple_spans(self):
        trace_id = "test-trace-002"
        with patch(
            "code_muse.plugins.trace_collector.store._traces_dir",
            return_value=Path(self.tmpdir),
        ):
            write_span(
                trace_id=trace_id,
                span_id="s1",
                parent_span_id=None,
                agent_name="muse",
                event_type="span_start",
            )
            write_span(
                trace_id=trace_id,
                span_id="s2",
                parent_span_id="s1",
                agent_name="retriever",
                event_type="span_start",
            )
            write_span(
                trace_id=trace_id,
                span_id="s2",
                parent_span_id="s1",
                agent_name="retriever",
                event_type="span_end",
                data={"success": True, "tokens": 150},
            )
            spans = load_trace(trace_id)
        assert len(spans) == 3

    def test_write_never_raises(self):
        """Write should silently fail, never crash."""
        with patch(
            "code_muse.plugins.trace_collector.store._traces_dir",
            side_effect=OSError("nope"),
        ):
            # This should not raise
            write_span(
                trace_id="bad-trace",
                span_id="s1",
                parent_span_id=None,
                agent_name="muse",
                event_type="span_start",
            )


# ---------------------------------------------------------------------------
# Tree building
# ---------------------------------------------------------------------------


class TestBuildTree:
    def test_single_root(self):
        spans = [
            {"span_id": "s1", "parent_span_id": None, "event_type": "span_start"},
        ]
        tree = build_tree(spans)
        assert tree["total_spans"] == 1
        assert len(tree["roots"]) == 1
        assert tree["roots"][0]["span_id"] == "s1"

    def test_parent_child(self):
        spans = [
            {"span_id": "s1", "parent_span_id": None, "agent_name": "muse"},
            {"span_id": "s2", "parent_span_id": "s1", "agent_name": "retriever"},
            {"span_id": "s3", "parent_span_id": "s1", "agent_name": "critic"},
        ]
        tree = build_tree(spans)
        assert tree["total_spans"] == 3
        root = tree["roots"][0]
        assert root["span_id"] == "s1"
        assert len(root["children"]) == 2

    def test_deep_nesting(self):
        spans = [
            {"span_id": "s1", "parent_span_id": None, "agent_name": "muse"},
            {"span_id": "s2", "parent_span_id": "s1", "agent_name": "retriever"},
            {"span_id": "s3", "parent_span_id": "s2", "agent_name": "terrier"},
        ]
        tree = build_tree(spans)
        root = tree["roots"][0]
        assert root["children"][0]["span_id"] == "s2"
        assert root["children"][0]["children"][0]["span_id"] == "s3"

    def test_empty_spans(self):
        tree = build_tree([])
        assert tree["total_spans"] == 0
        assert tree["roots"] == []
