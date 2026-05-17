"""Archival storage layer for completed task contexts.

Provides cold storage for completed tasks, allowing them to be recalled
later if needed. Each task is stored as a separate JSON file in the
task_archive directory.

Directory structure:
    ~/.muse/data/task_archive/
        task_<id>.json          # Archived messages + metadata
        task_<id>.json          # Another task
        ...

Each archive file contains:
    {
        "task_id": "...",
        "task_label": "...",
        "task_status": "archived",
        "created_at": "...",
        "completed_at": "...",
        "outcome_summary": "...",
        "message_count": int,
        "token_count": int,
        "messages": [...]  # Serialized messages (same format as session storage)
    }
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from code_muse.config.paths import DATA_DIR
from code_muse.plugins.task_context._text_utils import _extract_text
from code_muse.plugins.task_context.config import get_task_max_archive_contexts

logger = logging.getLogger(__name__)

# Archive directory: ~/.muse/data/task_archive/
ARCHIVE_DIR = DATA_DIR / "task_archive"


def _ensure_archive_dir() -> Path:
    """Create the archive directory if it doesn't exist."""
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    return ARCHIVE_DIR


def _archive_path(task_id: str) -> Path:
    """Return the file path for a task's archive."""
    # Sanitize task_id for filesystem use
    safe_name = task_id.replace("/", "_").replace("\\", "_").replace(":", "_")
    return ARCHIVE_DIR / f"{safe_name}.json"


def archive_messages_for_task(
    task_id: str,
    task_label: str,
    messages: list[Any],
    outcome_summary: str | None = None,
    completed_at: str | None = None,
) -> Path | None:
    """Archive messages for a completed task to cold storage.

    Args:
        task_id: Unique identifier for the task.
        task_label: Human-readable label for the task.
        messages: List of messages to archive.
        outcome_summary: Optional one-line summary of task outcome.
        completed_at: Optional ISO timestamp of completion (auto-generated if None).

    Returns:
        Path to the archive file, or None if archiving failed.
    """
    if not messages:
        logger.debug("No messages to archive for task %s", task_id[:8])
        return None

    try:
        _ensure_archive_dir()

        # Serialize messages
        serialized_messages = _serialize_messages(messages)

        archive_data = {
            "task_id": task_id,
            "task_label": task_label,
            "task_status": "archived",
            "created_at": _get_task_creation_time(task_id),
            "completed_at": completed_at or datetime.now().isoformat(),
            "archived_at": datetime.now().isoformat(),
            "outcome_summary": outcome_summary,
            "message_count": len(messages),
            "token_count": _estimate_archive_tokens(messages),
            "messages": serialized_messages,
        }

        path = _archive_path(task_id)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(archive_data, f, indent=2, default=str)

        logger.info(
            "Archived %d messages for task '%s' [%s] → %s",
            len(messages),
            task_label,
            task_id[:8],
            path,
        )

        # Cleanup old archives if over limit
        _cleanup_old_archives()

        return path

    except Exception as exc:
        logger.error("Failed to archive task %s: %s", task_id[:8], exc)
        return None


def recall_task_context(task_id: str) -> list[Any]:
    """Recall archived messages for a task.

    Args:
        task_id: The task_id to recall.

    Returns:
        List of messages (deserialized), or empty list if not found.
    """
    path = _archive_path(task_id)
    if not path.exists():
        logger.warning("No archive found for task %s", task_id[:8])
        return []

    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)

        messages = data.get("messages", [])
        deserialized = _deserialize_messages(messages)

        logger.info(
            "Recalled %d messages from task '%s' [%s]",
            len(deserialized),
            data.get("task_label", task_id[:8]),
            task_id[:8],
        )
        return deserialized

    except Exception as exc:
        logger.error("Failed to recall task %s: %s", task_id[:8], exc)
        return []


def delete_archive(task_id: str) -> bool:
    """Permanently delete an archived task's context.

    Args:
        task_id: The task_id to delete.

    Returns:
        True if the archive was deleted, False if not found.
    """
    path = _archive_path(task_id)
    if not path.exists():
        return False

    try:
        path.unlink()
        logger.info("Deleted archive for task %s", task_id[:8])
        return True
    except OSError as exc:
        logger.error("Failed to delete archive %s: %s", path, exc)
        return False


def list_archived_tasks() -> list[dict]:
    """List all archived tasks with their metadata.

    Returns:
        List of dicts with task_id, task_label, message_count, archived_at.
    """
    archive_dir = _ensure_archive_dir()
    tasks: list[dict] = []

    for path in sorted(archive_dir.glob("*.json")):
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            tasks.append(
                {
                    "task_id": data.get("task_id", path.stem),
                    "task_label": data.get("task_label", "(untitled)"),
                    "message_count": data.get("message_count", 0),
                    "token_count": data.get("token_count", 0),
                    "archived_at": data.get("archived_at", ""),
                    "outcome_summary": data.get("outcome_summary"),
                    "file_path": str(path),
                }
            )
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to read archive %s: %s", path, exc)

    return sorted(tasks, key=lambda t: t.get("archived_at", ""), reverse=True)


def get_archive_stats() -> dict:
    """Get summary statistics about the archive.

    Returns:
        Dict with total_archived_tasks, total_archived_messages, archive_size_bytes.
    """
    archive_dir = _ensure_archive_dir()
    total_tasks = 0
    total_messages = 0
    total_size = 0

    for path in archive_dir.glob("*.json"):
        total_tasks += 1
        total_size += path.stat().st_size
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            total_messages += data.get("message_count", 0)
        except json.JSONDecodeError, OSError:
            pass

    return {
        "total_archived_tasks": total_tasks,
        "total_archived_messages": total_messages,
        "archive_size_bytes": total_size,
        "archive_dir": str(archive_dir),
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _serialize_messages(messages: list[Any]) -> list[dict]:
    """Serialize messages for JSON storage.

    Uses the same approach as session_storage_helpers._wrap_messages
    for consistency, but works on a per-message level.
    """
    serialized: list[dict] = []
    for msg in messages:
        try:
            # Try pydantic-ai serialization
            from pydantic_ai.messages import ModelMessagesTypeAdapter

            dumped = ModelMessagesTypeAdapter.dump_python([msg], mode="json")
            if isinstance(dumped, list) and len(dumped) == 1:
                serialized.append(dumped[0])
                continue
        except Exception:
            pass

        # Fallback: extract text content
        text = _extract_text(msg)
        serialized.append(
            {
                "part_kind": "user-text",
                "content": text,
                "_fallback": True,
            }
        )

    return serialized


def _deserialize_messages(serialized: list[dict]) -> list[Any]:
    """Deserialize messages from JSON storage back to model messages.

    Uses pydantic-ai MessagesTypeAdapter for proper deserialization
    when possible, falls back to dict objects.
    """
    if not serialized:
        return []

    try:
        from pydantic_ai.messages import ModelMessagesTypeAdapter

        return ModelMessagesTypeAdapter.validate_python(serialized)
    except Exception:
        pass

    # Fallback: return as-is (dicts)
    return serialized


def _estimate_archive_tokens(messages: list[Any]) -> int:
    """Estimate total tokens for a list of messages (for metadata).

    Delegates to the core ``estimate_tokens`` helper (char/2.5 heuristic)
    so archival token counts stay consistent with compaction.
    """
    from code_muse.agents._history import estimate_tokens

    total = 0
    for msg in messages:
        text = _extract_text(msg)
        total += estimate_tokens(text)
    return total


def _get_task_creation_time(task_id: str) -> str:
    """Extract creation timestamp from task_id format 'task_YYMMDDHHMMSS_...'."""
    try:
        parts = task_id.split("_")
        if len(parts) >= 3:
            # Format: task_YYMMDDHHMMSS_shortuuid
            timestamp_str = parts[1]
            # Parse: 6 chars for YYMMDD + 6 chars for HHMMSS
            if len(timestamp_str) >= 12:
                from datetime import datetime as dt

                parsed = dt.strptime(timestamp_str, "%y%m%d%H%M%S")
                return parsed.isoformat()
    except (ValueError, IndexError):
        pass
    return datetime.now().isoformat()


def _cleanup_old_archives() -> None:
    """Remove oldest archive files if over the configured limit."""
    max_contexts = get_task_max_archive_contexts()
    if max_contexts <= 0:
        return

    archive_dir = _ensure_archive_dir()
    archives = sorted(archive_dir.glob("*.json"))

    if len(archives) <= max_contexts:
        return

    # Remove oldest archives (by file modification time)
    to_remove = archives[:-max_contexts]
    for path in to_remove:
        try:
            path.unlink()
            logger.debug("Cleaned up old archive: %s", path.name)
        except OSError as exc:
            logger.warning("Failed to clean up archive %s: %s", path, exc)
