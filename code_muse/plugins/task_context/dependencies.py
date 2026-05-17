"""File-cluster-based task dependency detection.

Tracks which files each task touches and auto-populates
cross_referenced_task_ids when tasks share file overlap.
"""

import logging
from collections import defaultdict
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# task_id -> set[file_path]
_task_files: dict[str, set[str]] = defaultdict(set)

# file_path -> set[task_id] (inverse index for fast lookup)
_file_tasks: dict[str, set[str]] = defaultdict(set)


def record_file_access(task_id: str, file_paths: list[str]) -> None:
    """Record that a task accessed certain files."""
    for fp in file_paths:
        _task_files[task_id].add(fp)
        _file_tasks[fp].add(task_id)


def get_task_files(task_id: str) -> set[str]:
    """Get all files touched by a task."""
    return _task_files.get(task_id, set())


def find_overlapping_tasks(task_id: str, min_overlap: int = 2) -> list[tuple[str, int]]:
    """Find tasks that share files with the given task.

    Returns list of (task_id, shared_file_count) sorted descending,
    filtered to tasks with >= min_overlap shared files.
    """
    files = _task_files.get(task_id, set())
    if not files:
        return []

    # Count overlaps
    overlap_counts: dict[str, int] = defaultdict(int)
    for fp in files:
        for tid in _file_tasks.get(fp, set()):
            if tid != task_id:
                overlap_counts[tid] += 1

    # Filter and sort
    result = [
        (tid, count) for tid, count in overlap_counts.items() if count >= min_overlap
    ]
    result.sort(key=lambda x: -x[1])
    return result


def get_all_dependency_edges() -> list[tuple[str, str, int]]:
    """Return all dependency edges as (source, target, overlap_count)."""
    edges: set[tuple[str, str, int]] = set()
    for tid, files in _task_files.items():
        for fp in files:
            for other_tid in _file_tasks.get(fp, set()):
                if tid < other_tid:  # Each edge once (lexicographic ordering)
                    overlap = len(_task_files[tid] & _task_files[other_tid])
                    if overlap >= 2:
                        edges.add((tid, other_tid, overlap))
    return sorted(edges, key=lambda x: -x[2])


def sync_cross_references(task_manager, min_overlap: int | None = None) -> int:
    """Auto-populate cross_referenced_task_ids from file overlap.

    Scans the dependency graph and adds cross-references to the TaskManager
    for any task pairs sharing >= min_overlap files.

    Returns the number of new cross-references added.
    """
    from code_muse.plugins.task_context.config import (
        get_task_dependency_file_overlap,
    )

    if min_overlap is None:
        min_overlap = get_task_dependency_file_overlap()

    edges = get_all_dependency_edges()
    added = 0
    for source, target, overlap in edges:
        if overlap >= min_overlap:
            # Check if cross-ref already exists
            src_task = task_manager.get_task(source)
            if src_task and target not in src_task.cross_referenced_task_ids:
                task_manager.add_cross_reference(source, target)
                added += 1
                logger.debug(
                    "Auto-linked tasks %s ↔ %s (%d shared files)",
                    source[:8],
                    target[:8],
                    overlap,
                )
    return added


def reset() -> None:
    """Clear all tracking (for testing)."""
    _task_files.clear()
    _file_tasks.clear()
