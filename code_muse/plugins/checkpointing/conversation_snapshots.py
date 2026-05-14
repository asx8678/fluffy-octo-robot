"""Conversation snapshot serialization for checkpointing."""

import orjson as json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from code_muse.agents import get_current_agent

logger = logging.getLogger(__name__)


def create_snapshot(
    agent: Any, tool_name: str, tool_call_id: str | None = None
) -> Path | None:
    """Serialize the current conversation state to a JSON snapshot."""
    try:
        if agent is None:
            agent = get_current_agent()

        messages = list(agent.get_message_history())
        timestamp = datetime.now(UTC).isoformat()

        snapshot: dict[str, Any] = {
            "turn_id": f"{tool_name}_{timestamp}",
            "timestamp": timestamp,
            "tool_name": tool_name,
            "tool_call_id": tool_call_id or "",
            "messages": _serialize_messages(messages),
            "agent_state": {
                "name": getattr(agent, "name", "unknown"),
                "model": getattr(agent, "model", "unknown"),
            },
        }

        # Store in shadow git repo area
        project_root = Path.cwd()
        project_hash = _hash_project_root(str(project_root))
        repo_path = Path.home() / ".muse" / "history" / project_hash
        snapshot_dir = repo_path / "snapshots"
        snapshot_dir.mkdir(parents=True, exist_ok=True)

        snapshot_path = snapshot_dir / f"snapshot_{timestamp.replace(':', '_')}.json"
        snapshot_path.write_text(orjson.dumps(snapshot, option=orjson.OPT_INDENT_2), encoding="utf-8")

        logger.info(f"Conversation snapshot saved to {snapshot_path}")
        return snapshot_path
    except Exception as exc:
        logger.error(f"Failed to create snapshot: {exc}")
        return None


def load_snapshot(path: Path) -> dict[str, Any] | None:
    """Load and validate a snapshot JSON file."""
    try:
        data = orjson.loads(path.read_text(encoding="utf-8"))
        required_keys = {"turn_id", "timestamp", "tool_name", "messages", "agent_state"}
        if not required_keys.issubset(data.keys()):
            logger.warning(f"Snapshot at {path} is missing required keys")
            return None
        return data
    except Exception as exc:
        logger.error(f"Failed to load snapshot {path}: {exc}")
        return None


def list_snapshots(repo_path: Path) -> list[dict[str, Any]]:
    """Scan snapshot directory and return metadata sorted newest-first."""
    snapshot_dir = repo_path / "snapshots"
    if not snapshot_dir.exists():
        return []

    results: list[dict[str, Any]] = []
    for path in snapshot_dir.glob("snapshot_*.json"):
        data = load_snapshot(path)
        if data is None:
            continue
        results.append(
            {
                "timestamp": data.get("timestamp", ""),
                "tool_name": data.get("tool_name", ""),
                "tool_call_id": data.get("tool_call_id", ""),
                "path": str(path),
            }
        )

    results.sort(key=lambda x: x["timestamp"], reverse=True)
    return results


def _hash_project_root(project_root: str) -> str:
    import hashlib

    return hashlib.sha256(project_root.encode()).hexdigest()


def _serialize_messages(messages: list[Any]) -> list[dict[str, Any]]:
    """Best-effort serialization of message history to JSON-safe dicts."""
    serialized: list[dict[str, Any]] = []
    for msg in messages:
        try:
            if hasattr(msg, "model_dump"):
                serialized.append(msg.model_dump())
            elif hasattr(msg, "dict"):
                serialized.append(msg.dict())
            else:
                serialized.append(
                    {
                        "type": type(msg).__name__,
                        "repr": repr(msg),
                    }
                )
        except Exception as exc:
            logger.warning(f"Could not serialize message: {exc}")
            serialized.append({"type": "unserializable", "error": str(exc)})
    return serialized
