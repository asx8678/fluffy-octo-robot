"""Durable JSONL backend for the Blackboard plugin.

When enabled, artifacts are appended to a JSONL file on every post and
loaded on startup.  Scope information is included in every record to
prevent cross-scope leakage even in the durable store.

The backend is append-only for writes (O(1) per post).  On startup,
the full file is replayed into the in-memory store.  Deleted/cleared
artifacts are handled by writing tombstone records.
"""

import json
import logging
from pathlib import Path
from typing import Any

from code_muse.plugins.blackboard.config import get_durable_path
from code_muse.plugins.blackboard.models import BlackboardArtifact

logger = logging.getLogger(__name__)

_TOMBSTONE = "__tombstone__"


def durable_post(artifact: BlackboardArtifact, path: Path | None = None) -> None:
    """Append an artifact record to the JSONL file."""
    if path is None:
        path = get_durable_path()
    record = artifact.model_dump(mode="json")
    record["_type"] = "artifact"
    _append_line(path, json.dumps(record))


def durable_delete(artifact_id: str, path: Path | None = None) -> None:
    """Write a tombstone record for a deleted artifact."""
    if path is None:
        path = get_durable_path()
    record = {"_type": _TOMBSTONE, "id": artifact_id}
    _append_line(path, json.dumps(record))


def durable_clear_scope(scope_key: str, path: Path | None = None) -> None:
    """Write a scope-clear tombstone record."""
    if path is None:
        path = get_durable_path()
    record = {"_type": "scope_clear", "scope_key": scope_key}
    _append_line(path, json.dumps(record))


def durable_load(
    path: Path | None = None,
) -> tuple[list[BlackboardArtifact], set[str], set[str]]:
    """Load all artifacts and tombstones from the JSONL file.

    Processes records in file order so that tombstones and scope
    clears correctly suppress previously-written artifacts.

    Returns:
        (artifacts, deleted_ids, cleared_scope_keys)
    """
    if path is None:
        path = get_durable_path()

    if not path.exists():
        return [], set(), set()

    # Order-preserving index of surviving artifacts by id
    surviving: dict[str, BlackboardArtifact] = {}
    deleted_ids: set[str] = set()
    cleared_scopes: set[str] = set()

    try:
        with open(path, encoding="utf-8") as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    record: dict[str, Any] = json.loads(line)
                except json.JSONDecodeError:
                    logger.warning(
                        "Durable blackboard: skipping invalid JSON at line %d",
                        line_num,
                    )
                    continue

                rec_type = record.get("_type")
                if rec_type == _TOMBSTONE:
                    del_id = record.get("id", "")
                    deleted_ids.add(del_id)
                    surviving.pop(del_id, None)
                elif rec_type == "scope_clear":
                    scope_key = record.get("scope_key", "")
                    cleared_scopes.add(scope_key)
                    # Remove all artifacts in the cleared scope
                    to_remove = [
                        aid
                        for aid, art in surviving.items()
                        if art.scope_key == scope_key
                    ]
                    for aid in to_remove:
                        surviving.pop(aid, None)
                elif rec_type == "artifact":
                    try:
                        art = BlackboardArtifact.model_validate(record)
                        if art.id in deleted_ids or art.scope_key in cleared_scopes:
                            continue  # tombstoned or scope cleared
                        surviving[art.id] = art
                    except Exception:
                        logger.warning(
                            "Durable blackboard: skipping invalid artifact at line %d",
                            line_num,
                        )
    except OSError as e:
        logger.warning("Durable blackboard: failed to read %s: %s", path, e)

    artifacts = list(surviving.values())
    return artifacts, deleted_ids, cleared_scopes


def durable_rebuild_clean(
    artifacts: list[BlackboardArtifact],
    path: Path | None = None,
) -> None:
    """Rewrite the JSONL file with only the surviving artifacts.

    Called after loading to compact the file and remove tombstones.
    """
    if path is None:
        path = get_durable_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            for artifact in artifacts:
                record = artifact.model_dump(mode="json")
                record["_type"] = "artifact"
                f.write(json.dumps(record) + "\n")
    except OSError as e:
        logger.warning("Durable blackboard: failed to rebuild %s: %s", path, e)


def _append_line(path: Path, line: str) -> None:
    """Append a single line to the JSONL file (creating it if needed)."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError as e:
        logger.warning("Durable blackboard: failed to append to %s: %s", path, e)
