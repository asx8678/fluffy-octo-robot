"""Experience store — per-repo JSONL storage for experience capsules.

Storage layout:
    ~/.muse/data/experience_store/
        <repo_hash>.jsonl       # Per-repo capsules
        _global.jsonl           # Global cross-repo capsules (opt-in)

Each line in a JSONL file is a single ExperienceCapsule JSON object.
"""

import hashlib
import json
import logging
import os
from pathlib import Path

from code_muse.config.paths import DATA_DIR
from code_muse.plugins.task_context.experience_models import ExperienceCapsule
from code_muse.plugins.task_context.experience_signature import (
    compute_capsule_signature,
    redact_for_signature,
    search_capsules,
)

logger = logging.getLogger(__name__)

# Base directory for all experience stores
EXPERIENCE_STORE_DIR = DATA_DIR / "experience_store"

# Global store filename
_GLOBAL_STORE_NAME = "_global.jsonl"


# ---------------------------------------------------------------------------
# Repo scope hashing
# ---------------------------------------------------------------------------


def _repo_hash_from_path(path: str) -> str:
    """Deterministic short hash of a repo root path.

    Uses SHA-256 truncated to 16 hex chars. The hash prevents
    raw path leakage in filenames while being deterministic.
    """
    return hashlib.sha256(path.encode("utf-8")).hexdigest()[:16]


def _detect_repo_root() -> str:
    """Best-effort detection of the current git repo root.

    Falls back to cwd if not in a git repo.
    """
    try:
        import subprocess

        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=2,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except Exception:
        pass
    return os.getcwd()


def get_repo_scope() -> str:
    """Get the current repo scope hash."""
    root = _detect_repo_root()
    return _repo_hash_from_path(root)


# ---------------------------------------------------------------------------
# Store path helpers
# ---------------------------------------------------------------------------


def _ensure_store_dir() -> Path:
    """Create the experience store directory if it doesn't exist."""
    EXPERIENCE_STORE_DIR.mkdir(parents=True, exist_ok=True)
    return EXPERIENCE_STORE_DIR


def get_store_path(repo_scope: str | None = None) -> Path:
    """Get the JSONL store path for the given (or current) repo scope."""
    _ensure_store_dir()
    if repo_scope is None:
        repo_scope = get_repo_scope()
    return EXPERIENCE_STORE_DIR / f"{repo_scope}.jsonl"


def get_global_store_path() -> Path:
    """Get the path for the global cross-repo store."""
    _ensure_store_dir()
    return EXPERIENCE_STORE_DIR / _GLOBAL_STORE_NAME


# ---------------------------------------------------------------------------
# CRUD operations
# ---------------------------------------------------------------------------


def store_capsule(capsule: ExperienceCapsule) -> None:
    """Append a capsule to the appropriate store(s).

    Always stores in the per-repo store. If global is enabled,
    also stores in the global store.
    """
    from code_muse.plugins.task_context.config import (
        get_experience_global_enabled,
        get_experience_max_capsules,
    )

    # Per-repo store
    repo_path = get_store_path(capsule.repo_scope)
    _append_capsule(repo_path, capsule)

    # Global store (if opted in)
    if get_experience_global_enabled():
        global_path = get_global_store_path()
        _append_capsule(global_path, capsule)

    # Enforce max capsules (prune oldest from bottom of file)
    max_caps = get_experience_max_capsules()
    _enforce_capsule_limit(repo_path, max_caps)
    if get_experience_global_enabled():
        _enforce_capsule_limit(get_global_store_path(), max_caps)

    logger.info(
        "Stored experience capsule %s for repo %s",
        capsule.capsule_id[:8],
        capsule.repo_scope[:8],
    )


def _append_capsule(path: Path, capsule: ExperienceCapsule) -> None:
    """Append a single capsule as a JSON line to a JSONL file."""
    _ensure_store_dir()
    with open(path, "a", encoding="utf-8") as f:
        line = capsule.model_dump_json()
        f.write(line + "\n")


def _enforce_capsule_limit(path: Path, max_caps: int) -> None:
    """Keep only the most recent max_caps capsules in a store file."""
    if not path.exists():
        return
    try:
        lines = path.read_text(encoding="utf-8").strip().split("\n")
        if len(lines) <= max_caps:
            return
        # Keep the most recent (last N lines)
        kept = lines[-max_caps:]
        path.write_text("\n".join(kept) + "\n", encoding="utf-8")
    except Exception as exc:
        logger.warning("Failed to enforce capsule limit on %s: %s", path, exc)


def load_capsules(store_path: Path | None = None) -> list[ExperienceCapsule]:
    """Load all capsules from a store file.

    Args:
        store_path: Path to the JSONL file. If None, uses current repo scope.
    """
    if store_path is None:
        store_path = get_store_path()

    if not store_path.exists():
        return []

    capsules: list[ExperienceCapsule] = []
    try:
        text = store_path.read_text(encoding="utf-8").strip()
        if not text:
            return []
        for line in text.split("\n"):
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                capsules.append(ExperienceCapsule.model_validate(data))
            except Exception as exc:
                logger.warning("Skipping malformed capsule line: %s", exc)
    except Exception as exc:
        logger.error("Failed to load capsules from %s: %s", store_path, exc)

    return capsules


def load_all_relevant_capsules() -> list[ExperienceCapsule]:
    """Load capsules from the repo store + global store (if enabled)."""
    from code_muse.plugins.task_context.config import get_experience_global_enabled

    repo_capsules = load_capsules(get_store_path())

    if get_experience_global_enabled():
        global_capsules = load_capsules(get_global_store_path())
        # Deduplicate by capsule_id
        seen = {c.capsule_id for c in repo_capsules}
        for c in global_capsules:
            if c.capsule_id not in seen:
                repo_capsules.append(c)
                seen.add(c.capsule_id)

    return repo_capsules


def delete_capsule(capsule_id: str, repo_scope: str | None = None) -> bool:
    """Delete a capsule by ID from the store.

    Returns True if found and deleted, False otherwise.
    """
    if repo_scope is None:
        repo_scope = get_repo_scope()

    path = get_store_path(repo_scope)
    capsules = load_capsules(path)
    original_len = len(capsules)
    capsules = [c for c in capsules if c.capsule_id != capsule_id]

    if len(capsules) >= original_len:
        return False

    # Rewrite file without the deleted capsule
    _rewrite_store(path, capsules)

    # Also try global store
    global_path = get_global_store_path()
    if global_path.exists():
        global_caps = load_capsules(global_path)
        global_caps = [c for c in global_caps if c.capsule_id != capsule_id]
        _rewrite_store(global_path, global_caps)

    logger.info("Deleted experience capsule %s", capsule_id[:8])
    return True


def _rewrite_store(path: Path, capsules: list[ExperienceCapsule]) -> None:
    """Rewrite a JSONL store with the given capsules."""
    _ensure_store_dir()
    lines = [c.model_dump_json() for c in capsules]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


# ---------------------------------------------------------------------------
# Search / retrieval
# ---------------------------------------------------------------------------


def search_experience(
    query: str,
    top_k: int | None = None,
    min_similarity: float = 0.3,
) -> list[tuple[ExperienceCapsule, float]]:
    """Search for capsules similar to the query.

    Args:
        query: Search text.
        top_k: Max results (default from config).
        min_similarity: Minimum similarity threshold.

    Returns:
        List of (capsule, similarity) tuples, sorted descending.
    """
    from code_muse.plugins.task_context.config import get_experience_max_results

    if top_k is None:
        top_k = get_experience_max_results()

    capsules = load_all_relevant_capsules()
    return search_capsules(
        query=query,
        capsules=capsules,
        top_k=top_k,
        min_similarity=min_similarity,
    )


# ---------------------------------------------------------------------------
# Backfill from task archives
# ---------------------------------------------------------------------------


def backfill_experiences_from_archives(
    repo_scope: str | None = None,
) -> int:
    """Scan task_archive/ and create capsules for any missing tasks.

    Returns the number of new capsules created.
    """
    from code_muse.plugins.task_context.archival import list_archived_tasks

    if repo_scope is None:
        repo_scope = get_repo_scope()

    # Load existing capsule task_ids to avoid duplicates
    existing_path = get_store_path(repo_scope)
    existing_capsules = load_capsules(existing_path)
    existing_task_ids = {c.task_id for c in existing_capsules}

    archived = list_archived_tasks()
    created = 0

    for archive_meta in archived:
        task_id = archive_meta.get("task_id", "")
        if not task_id or task_id in existing_task_ids:
            continue

        try:
            capsule = _capsule_from_archive(archive_meta, repo_scope)
            if capsule:
                _append_capsule(existing_path, capsule)
                existing_task_ids.add(task_id)
                created += 1
        except Exception as exc:
            logger.warning(
                "Failed to backfill capsule for task %s: %s",
                task_id[:8],
                exc,
            )

    logger.info("Backfilled %d experience capsules from archives", created)
    return created


def _capsule_from_archive(
    archive_meta: dict,
    repo_scope: str,
) -> ExperienceCapsule | None:
    """Create an ExperienceCapsule from an archive metadata dict."""
    task_id = archive_meta.get("task_id", "")
    task_label = archive_meta.get("task_label", "")
    outcome_summary = archive_meta.get("outcome_summary") or ""

    if not task_label and not outcome_summary:
        return None

    # Build combined text for signature
    key_terms, semantic_signature, structural_fingerprint = compute_capsule_signature(
        task_label=task_label,
        outcome_summary=outcome_summary,
        summary="",
        metadata=None,
    )

    return ExperienceCapsule(
        task_id=task_id,
        task_label=task_label,
        outcome_summary=outcome_summary,
        repo_scope=repo_scope,
        source_archive_path=archive_meta.get("file_path", ""),
        summary=outcome_summary[:500] if outcome_summary else "",
        key_terms=key_terms,
        semantic_signature=semantic_signature,
        structural_fingerprint=structural_fingerprint,
        token_estimate=archive_meta.get("token_count", 0),
        metadata={
            "backfilled": True,
            "message_count": archive_meta.get("message_count", 0),
        },
    )


# ---------------------------------------------------------------------------
# Capsule creation from completed task
# ---------------------------------------------------------------------------


def create_capsule_from_task(
    task_id: str,
    task_label: str,
    outcome_summary: str | None = None,
    summary: str = "",
    token_estimate: int = 0,
    tools_used: list[str] | None = None,
    file_types: list[str] | None = None,
    source_archive_path: str = "",
    metadata: dict | None = None,
) -> ExperienceCapsule:
    """Create and store an ExperienceCapsule from a completed task.

    Returns the newly created capsule.
    """
    repo_scope = get_repo_scope()
    outcome = outcome_summary or ""
    combined_text = f"{task_label} {outcome} {summary}"

    # Redact before computing signature
    redacted = redact_for_signature(combined_text)
    key_terms, semantic_signature, structural_fingerprint = compute_capsule_signature(
        task_label=task_label,
        outcome_summary=outcome,
        summary=summary,
        metadata=metadata,
    )

    # Add tool/file info to structural fingerprint
    fp = structural_fingerprint.copy()
    if tools_used:
        fp["tools_used"] = sorted(set(tools_used))
    if file_types:
        fp["file_types"] = sorted(set(file_types))

    capsule = ExperienceCapsule(
        task_id=task_id,
        task_label=task_label,
        outcome_summary=outcome,
        repo_scope=repo_scope,
        source_archive_path=source_archive_path,
        summary=redacted[:500],
        key_terms=key_terms,
        semantic_signature=semantic_signature,
        structural_fingerprint=fp,
        token_estimate=token_estimate,
        metadata=metadata or {},
    )

    store_capsule(capsule)
    return capsule


# ---------------------------------------------------------------------------
# Store stats
# ---------------------------------------------------------------------------


def get_capsule_count(repo_scope: str | None = None) -> int:
    """Get the number of capsules in the current repo store."""
    path = get_store_path(repo_scope)
    if not path.exists():
        return 0
    try:
        text = path.read_text(encoding="utf-8").strip()
        if not text:
            return 0
        return len([line for line in text.split("\n") if line.strip()])
    except Exception:
        return 0


def list_capsules(repo_scope: str | None = None) -> list[ExperienceCapsule]:
    """List all capsules in the current repo store."""
    return load_capsules(get_store_path(repo_scope))
