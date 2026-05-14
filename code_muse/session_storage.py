"""Session persistence layer - public API (save, load, list, cleanup)."""

import orjson as json
from pathlib import Path
from typing import Any

import aiofiles

from code_muse.session_storage_helpers import (  # noqa: F401
    _FORMAT,
    _LAST_SAVED_HASHES,
    _LEGACY_SIGNATURE_SIZE,
    _LEGACY_SIGNED_HEADER,
    _SCHEMA_VERSION,
    _UNABLE_TO_LOAD,
    SessionHistory,
    SessionMetadata,
    SessionPaths,
    TokenEstimator,
    _atomic_write_json,
    _canonical_json_path,
    _hash_session_data,
    _is_binary_pickle,
    _try_load_pkl,
    _unsafe_pickle_loads_for_explicit_legacy_migration_only,
    _unwrap_messages,
    _wrap_messages,
    build_session_paths,
    ensure_directory,
)


def save_session(
    *,
    history: Any,
    session_name: str,
    base_dir: Path,
    timestamp: str,
    token_estimator: TokenEstimator,
    auto_saved: bool = False,
) -> SessionMetadata:
    ensure_directory(base_dir)
    paths = build_session_paths(base_dir, session_name)
    json_path = _canonical_json_path(base_dir, session_name)

    session_data = _wrap_messages(history)

    # Compute token count once (used in both dirty-hit and write paths)
    total_tokens = sum(token_estimator(message) for message in history)

    # Dirty-flag check: skip disk writes if the session data is unchanged
    hash_key = (str(base_dir), session_name)
    current_hash = _hash_session_data(session_data)
    if current_hash is not None and _LAST_SAVED_HASHES.get(hash_key) == current_hash:
        return SessionMetadata(
            session_name=session_name,
            timestamp=timestamp,
            message_count=len(history),
            total_tokens=total_tokens,
            pickle_path=paths.pickle_path,
            metadata_path=paths.metadata_path,
            auto_saved=auto_saved,
        )

    _LAST_SAVED_HASHES[hash_key] = current_hash

    # Write canonical .json file
    _atomic_write_json(json_path, session_data)

    # Write compat .pkl file (same JSON content, different extension)
    _atomic_write_json(paths.pickle_path, session_data)

    metadata = SessionMetadata(
        session_name=session_name,
        timestamp=timestamp,
        message_count=len(history),
        total_tokens=total_tokens,
        pickle_path=paths.pickle_path,
        metadata_path=paths.metadata_path,
        auto_saved=auto_saved,
    )

    _atomic_write_json(paths.metadata_path, metadata.as_serialisable())

    return metadata


def load_session(
    session_name: str, base_dir: Path, *, allow_legacy: bool = False
) -> Any:
    # 1. Try canonical .json first
    json_path = _canonical_json_path(base_dir, session_name)
    if json_path.exists():
        with json_path.open("r", encoding="utf-8") as f:
            data = orjson.loads(f.read())
        return _unwrap_messages(data)

    # 2. Try compat .pkl path
    paths = build_session_paths(base_dir, session_name)
    if paths.pickle_path.exists():
        result = _try_load_pkl(paths.pickle_path, allow_legacy=allow_legacy)
        if result is not _UNABLE_TO_LOAD:
            return result

    # 3. Legacy .pkl without compat path
    legacy_path = base_dir / f"{session_name}.pkl"
    if legacy_path.exists() and not paths.pickle_path.exists():
        result = _try_load_pkl(legacy_path, allow_legacy=allow_legacy)
        if result is not _UNABLE_TO_LOAD:
            return result

    raise FileNotFoundError(json_path)


def _pkl_is_known_session(path: Path) -> bool:
    """Check whether a .pkl file is a recognized session file.

    A .pkl file is considered a session if it has accompanying metadata,
    contains JSON data (written by current save_session), or is empty
    (placeholder).  Arbitrary raw pickle files without metadata are excluded
    for security.
    """
    try:
        raw = path.read_bytes()
    except OSError:
        return False
    if not raw:
        return True  # empty placeholder
    return not _is_binary_pickle(raw)


def list_sessions(base_dir: Path) -> list[str]:
    if not base_dir.exists():
        return []

    seen: set[str] = set()
    names: list[str] = []

    # Include .json sessions (canonical)
    for path in base_dir.glob("*.json"):
        if path.name.endswith("_meta.json"):
            continue
        name = path.stem
        if name not in seen:
            seen.add(name)
            names.append(name)

    # Include .pkl sessions if they have _meta.json OR contain JSON data
    # or are empty placeholders. Arbitrary raw pickle files (no metadata,
    # binary content) are excluded for security.
    for path in base_dir.glob("*.pkl"):
        name = path.stem
        if name in seen:
            continue
        meta_path = base_dir / f"{name}_meta.json"
        if meta_path.exists() or _pkl_is_known_session(path):
            seen.add(name)
            names.append(name)

    return sorted(names)


def cleanup_sessions(base_dir: Path, max_sessions: int) -> list[str]:
    if max_sessions <= 0:
        return []

    if not base_dir.exists():
        return []

    # Gather all session names (from .json and .pkl files, excluding metadata)
    seen_names: set[str] = set()
    for ext in ("*.json", "*.pkl"):
        for path in base_dir.glob(ext):
            if path.name.endswith("_meta.json"):
                continue
            seen_names.add(path.stem)

    if len(seen_names) <= max_sessions:
        return []

    # For each session, determine mtime from the most relevant file:
    # prefer .pkl (what old callers set mtime on), then _meta.json, then .json
    candidate_paths: list[tuple[float, str]] = []
    for name in sorted(seen_names):
        mtime: float | None = None
        for candidate in (
            base_dir / f"{name}.pkl",
            base_dir / f"{name}_meta.json",
            base_dir / f"{name}.json",
        ):
            try:
                mtime = candidate.stat().st_mtime
                break
            except OSError:
                continue
        if mtime is not None:
            candidate_paths.append((mtime, name))

    if len(candidate_paths) <= max_sessions:
        return []

    sorted_candidates = sorted(candidate_paths, key=lambda item: item[0])

    stale_entries = sorted_candidates[:-max_sessions]
    removed_sessions: list[str] = []
    for _, name in stale_entries:
        # Remove all sibling files for this session
        for sibling in (
            base_dir / f"{name}.json",
            base_dir / f"{name}.pkl",
            base_dir / f"{name}_meta.json",
        ):
            try:
                sibling.unlink(missing_ok=True)
            except OSError:
                continue
        removed_sessions.append(name)

    return removed_sessions


async def restore_autosave_interactively(base_dir: Path) -> None:
    """Prompt the user to load an autosave session from base_dir, if any exist.

    This helper is deliberately placed in session_storage to keep autosave
    restoration close to the persistence layer. It uses the same public APIs
    (list_sessions, load_session) and mirrors the interactive behaviours from
    the command handler.
    """
    sessions = list_sessions(base_dir)
    if not sessions:
        return

    # Import locally to avoid pulling the messaging layer into storage modules
    from datetime import datetime

    from prompt_toolkit.formatted_text import FormattedText

    from code_muse.agents.agent_manager import get_current_agent
    from code_muse.command_line.prompt_toolkit_completion import (
        get_input_with_combined_completion,
    )
    from code_muse.messaging import emit_success, emit_system_message, emit_warning

    entries = []
    for name in sessions:
        meta_path = base_dir / f"{name}_meta.json"
        try:
            async with aiofiles.open(meta_path, encoding="utf-8") as meta_file:
                data = orjson.loads(await meta_file.read())
            timestamp = data.get("timestamp")
            message_count = data.get("message_count")
        except Exception:
            timestamp = None
            message_count = None
        entries.append((name, timestamp, message_count))

    def sort_key(entry):
        _, timestamp, _ = entry
        if timestamp:
            try:
                return datetime.fromisoformat(timestamp)
            except ValueError:
                return datetime.min
        return datetime.min

    entries.sort(key=sort_key, reverse=True)

    PAGE_SIZE = 5
    total = len(entries)
    page = 0

    def render_page() -> None:
        start = page * PAGE_SIZE
        end = min(start + PAGE_SIZE, total)
        page_entries = entries[start:end]
        emit_system_message("Autosave Sessions Available:")
        for idx, (name, timestamp, message_count) in enumerate(page_entries, start=1):
            timestamp_display = timestamp or "unknown time"
            message_display = (
                f"{message_count} messages"
                if message_count is not None
                else "unknown size"
            )
            emit_system_message(
                f"  [{idx}] {name} ({message_display}, saved at {timestamp_display})"
            )
        # If more pages: show next-page; on last page show 'Return to first page'
        if total > PAGE_SIZE:
            page_count = (total + PAGE_SIZE - 1) // PAGE_SIZE
            is_last_page = (page + 1) >= page_count
            remaining = total - (page * PAGE_SIZE + len(page_entries))
            summary = (
                f" and {remaining} more" if (remaining > 0 and not is_last_page) else ""
            )
            label = "Return to first page" if is_last_page else f"Next page{summary}"
            emit_system_message(f"  [6] {label}")
        emit_system_message("  [Enter] Skip loading autosave")

    chosen_name: str | None = None

    while True:
        render_page()
        try:
            selection = await get_input_with_combined_completion(
                FormattedText(
                    [
                        (
                            "class:prompt",
                            "Pick 1-5 to load, 6 for next, or name/Enter: ",
                        )
                    ]
                )
            )
        except KeyboardInterrupt, EOFError:
            emit_warning("Autosave selection cancelled")
            return

        selection = (selection or "").strip()
        if not selection:
            return

        # Numeric choice: 1-5 select within current page; 6 advances page
        if selection.isdigit():
            num = int(selection)
            if num == 6 and total > PAGE_SIZE:
                page = (page + 1) % ((total + PAGE_SIZE - 1) // PAGE_SIZE)
                # loop and re-render next page
                continue
            if 1 <= num <= 5:
                start = page * PAGE_SIZE
                idx = start + (num - 1)
                if 0 <= idx < total:
                    chosen_name = entries[idx][0]
                    break
                else:
                    emit_warning("Invalid selection for this page")
                    continue
            emit_warning("Invalid selection; choose 1-5 or 6 for next")
            continue

        # Allow direct typing by exact session name
        for name, _ts, _mc in entries:
            if name == selection:
                chosen_name = name
                break
        if chosen_name:
            break
        emit_warning("No autosave loaded (invalid selection)")
        # keep looping and allow another try

    if not chosen_name:
        return

    try:
        history = load_session(chosen_name, base_dir, allow_legacy=True)
    except FileNotFoundError:
        emit_warning(f"Autosave '{chosen_name}' could not be found")
        return
    except Exception as exc:
        emit_warning(f"Failed to load autosave '{chosen_name}': {exc}")
        return

    agent = get_current_agent()
    agent.set_message_history(history)

    # Set current autosave session id so subsequent autosaves overwrite this session
    from code_muse.config.session import set_current_autosave_from_session_name

    set_current_autosave_from_session_name(chosen_name)

    total_tokens = sum(agent.estimate_tokens_for_message(msg) for msg in history)

    session_path = base_dir / f"{chosen_name}.json"
    emit_success(
        f"✅ Autosave loaded: {len(history)} messages ({total_tokens} tokens)\n"
        f"📁 From: {session_path}"
    )

    # Display recent message history for context
    try:
        from code_muse.command_line.autosave_menu import display_resumed_history

        display_resumed_history(history)
    except Exception:
        pass  # Don't fail if display doesn't work in non-TTY environment
