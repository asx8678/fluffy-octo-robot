"""Trace store — persisted NDJSON trace data with query support.

Writes structured span data to ``~/.muse/traces/`` for post-hoc
debugging of multi-agent invocation trees.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

from code_muse.config import paths as muse_paths

logger = logging.getLogger(__name__)

_MAX_ROTATION_SIZE = 10 * 1024 * 1024  # 10 MB per trace file


def _traces_dir() -> Path:
    """Return the directory for trace NDJSON files."""
    state_dir = getattr(muse_paths, "STATE_DIR", None)
    if state_dir is not None:
        return Path(state_dir) / "traces"
    return Path.home() / ".muse" / "traces"


def _trace_path(trace_id: str) -> Path:
    """Return the file path for a specific trace."""
    # Sanitise trace_id for filesystem use
    safe_id = trace_id.replace("/", "_").replace("\\", "_")[:48]
    return _traces_dir() / f"trace_{safe_id}.ndjson"


def _rotate_if_needed(path: Path) -> None:
    """Rotate a trace file if it exceeds the size limit."""
    try:
        if path.exists() and path.stat().st_size >= _MAX_ROTATION_SIZE:
            rotated = path.with_suffix(f".ndjson.{int(time.time())}")
            path.rename(rotated)
            logger.info("Rotated trace file: %s → %s", path, rotated)
    except OSError:
        logger.debug("Could not rotate trace file %s", path)


def write_span(
    trace_id: str,
    span_id: str,
    parent_span_id: str | None,
    agent_name: str,
    event_type: str,
    data: dict[str, Any] | None = None,
    turn: int = 0,
    swarm_id: str | None = None,
) -> None:
    """Append a span event to the trace NDJSON file.

    Each line is a self-contained JSON object with trace context,
    making files both append-friendly and grep-friendly.

    Never raises — all I/O is best-effort.
    """
    try:
        path = _trace_path(trace_id)
        _rotate_if_needed(path)
        path.parent.mkdir(parents=True, exist_ok=True)

        entry: dict[str, Any] = {
            "timestamp": time.time(),
            "trace_id": trace_id,
            "span_id": span_id,
            "parent_span_id": parent_span_id,
            "agent_name": agent_name,
            "event_type": event_type,
            "turn": turn,
            **(data or {}),
        }
        if swarm_id:
            entry["swarm_id"] = swarm_id

        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, default=str) + "\n")
    except OSError:
        logger.debug("Could not write trace span for trace_id=%s", trace_id[:8])


def load_trace(trace_id: str) -> list[dict[str, Any]]:
    """Load all spans for a given trace from the NDJSON file.

    Returns an empty list if the file doesn't exist.
    """
    path = _trace_path(trace_id)
    if not path.exists():
        return []

    spans: list[dict[str, Any]] = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    spans.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError:
        logger.debug("Could not read trace file for trace_id=%s", trace_id[:8])

    return spans


def build_tree(spans: list[dict[str, Any]]) -> dict[str, Any]:
    """Build a parent→child tree from flat span data.

    Returns a dict with ``root`` spans (those with no parent) and
    ``children`` nested recursively.
    """
    by_span_id: dict[str, dict[str, Any]] = {}
    children_map: dict[str | None, list[dict[str, Any]]] = {}

    for span in spans:
        span_id = span.get("span_id", "unknown")
        by_span_id[span_id] = span
        parent = span.get("parent_span_id")
        children_map.setdefault(parent, []).append(span)

    def _build_node(span_id: str) -> dict[str, Any]:
        node = dict(by_span_id.get(span_id, {}))
        node["children"] = [
            _build_node(child["span_id"]) for child in children_map.get(span_id, [])
        ]
        return node

    roots = children_map.get(None, [])
    return {
        "trace_id": spans[0].get("trace_id") if spans else None,
        "roots": [_build_node(r["span_id"]) for r in roots],
        "total_spans": len(spans),
    }
