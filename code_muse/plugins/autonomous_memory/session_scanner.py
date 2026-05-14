"""Session scanner for the Autonomous Memory Pipeline.

Discovers eligible past sessions based on message count, activity status,
and idle time. Tracks processed sessions via a persistent state file.
"""

import hashlib
import orjson as json
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

IDLE_THRESHOLD_SECONDS = 10_800  # 3 hours
ACTIVE_THRESHOLD_SECONDS = 1_800  # 30 minutes
MIN_MESSAGE_COUNT = 10


@dataclass
class SessionInfo:
    """Summary of a discovered session directory."""

    path: Path
    message_count: int
    last_active: float
    is_active: bool
    processed: bool


def _find_messages_file(session_dir: Path) -> Path | None:
    """Locate the messages file (messages.json or any .jsonl) in a session dir."""
    candidates = [
        session_dir / "messages.json",
        *session_dir.glob("*.jsonl"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _count_user_messages(messages_path: Path) -> int:
    """Count lines that appear to contain a user message."""
    try:
        with messages_path.open("r", encoding="utf-8") as fh:
            return sum(
                1 for line in fh if '"role": "user"' in line or '"role":"user"' in line
            )
    except Exception as exc:
        logger.warning(f"Failed to count messages in {messages_path}: {exc}")
        return 0


def _read_state(state_file: Path) -> dict[str, Any]:
    """Read the processed-sessions state file."""
    if not state_file.exists():
        return {"processed": []}
    try:
        with state_file.open("r", encoding="utf-8") as fh:
            data = orjson.loads(fh.read())
            if isinstance(data, dict) and isinstance(data.get("processed"), list):
                return data
    except Exception as exc:
        logger.warning(f"Corrupt state file {state_file}: {exc}")
    return {"processed": []}


def _write_state(state_file: Path, data: dict[str, Any]) -> None:
    """Persist the processed-sessions state file."""
    state_file.parent.mkdir(parents=True, exist_ok=True)
    with state_file.open("w", encoding="utf-8") as fh:
        fh.write(orjson.dumps(data, option=orjson.OPT_INDENT_2).decode())


def scan_eligible_sessions(sessions_dir: Path, state_file: Path) -> list[SessionInfo]:
    """Scan for sessions that are eligible for memory extraction.

    Filters:
      - message_count >= 10
      - not currently active
      - idle > 3 hours
      - not already processed

    Results are sorted by ``last_active`` descending (most recent first).
    """
    if not sessions_dir.exists():
        return []

    state = _read_state(state_file)
    processed_paths: set[str] = set(state.get("processed", []))
    now = time.time()
    sessions: list[SessionInfo] = []

    for entry in sessions_dir.iterdir():
        if not entry.is_dir():
            continue

        messages_file = _find_messages_file(entry)
        if messages_file is None:
            continue

        msg_count = _count_user_messages(messages_file)
        last_active = messages_file.stat().st_mtime
        idle_seconds = now - last_active

        # Active = has a lock file OR recent mtime (< 30 min)
        lock_file = entry / ".session_lock"
        is_active = lock_file.exists() or idle_seconds < ACTIVE_THRESHOLD_SECONDS

        session_path_str = str(entry)
        processed = session_path_str in processed_paths

        if msg_count < MIN_MESSAGE_COUNT:
            continue
        if is_active:
            continue
        if idle_seconds <= IDLE_THRESHOLD_SECONDS:
            continue
        if processed:
            continue

        sessions.append(
            SessionInfo(
                path=entry,
                message_count=msg_count,
                last_active=last_active,
                is_active=is_active,
                processed=processed,
            )
        )

    sessions.sort(key=lambda s: s.last_active, reverse=True)
    return sessions


def mark_session_processed(state_file: Path, session_path: str) -> None:
    """Record a session as processed so it won't be re-scanned."""
    state = _read_state(state_file)
    processed: list[str] = state.get("processed", [])
    if session_path not in processed:
        processed.append(session_path)
        state["processed"] = processed
        _write_state(state_file, state)


def get_sessions_dir() -> Path:
    """Return the global sessions storage directory."""
    return Path.home() / ".muse" / "sessions"


def get_memory_dir(project_hash: str) -> Path:
    """Return the memory storage directory for a given project hash."""
    return Path.home() / ".muse" / "memory" / project_hash


def get_project_hash(cwd: str | None = None) -> str:
    """Compute a 12-char project hash from the working directory."""
    cwd = cwd or os.getcwd()
    return hashlib.sha256(cwd.encode()).hexdigest()[:12]
