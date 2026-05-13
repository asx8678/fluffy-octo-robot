"""Shared helpers for persisting and restoring chat sessions.

This module centralises JSON session handling using pydantic-ai message
serialization.  Pickle is no longer the default; legacy pickle files are
rejected unless an explicit migration flag is provided.

Backward compatibility:
  - ``build_session_paths()`` returns ``.pkl`` extension for ``pickle_path``
    to match legacy callers, but the file actually contains JSON.
  - ``save_session()`` writes JSON to both ``.json`` (canonical) and
    ``.pkl`` (compat) paths so old code checking for ``.pkl`` still works.
  - ``load_session()`` prefers ``.json``; falls back to ``.pkl``; and only
    loads binary pickle when ``allow_legacy=True``.
  - ``_unwrap_messages()`` gracefully handles plain dicts/lists/strings when
    the payload does not conform to the pydantic-ai schema.
  - ``list_sessions()`` includes ``.json`` sessions and ``.pkl`` sessions
    that have matching ``_meta.json`` metadata.
  - ``cleanup_sessions()`` removes stale ``.json``, ``.pkl``, and
    ``_meta.json`` files.
"""

import hashlib
import hmac
import json
import os
import pickle
import warnings
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import aiofiles
from pydantic_ai.messages import ModelMessage, ModelMessagesTypeAdapter

_LEGACY_SIGNED_HEADER = b"CPSESSION\x01"
_LEGACY_SIGNATURE_SIZE = 32  # retained only for backward-compat parsing

SessionHistory = list[ModelMessage]
TokenEstimator = Callable[[Any], int]

_SCHEMA_VERSION = "muse.session.v1"
_FORMAT = "pydantic-ai-model-messages-json"

# Sentinel for _try_load_pkl when file cannot be loaded
_UNABLE_TO_LOAD = object()

# Per-session hash cache to avoid redundant writes when data is unchanged
_LAST_SAVED_HASHES: dict[tuple[str, str], str | None] = {}


def _hash_session_data(data: dict[str, Any]) -> str | None:
    """Return a SHA-256 hash of serialised session data for dirty-flag comparison."""
    try:
        return hashlib.sha256(
            json.dumps(data, sort_keys=True).encode("utf-8")
        ).hexdigest()
    except TypeError, ValueError:
        return None


def _unsafe_pickle_loads_for_explicit_legacy_migration_only(data: bytes) -> Any:
    """Deserialize pickle data with a loud warning.

    This function is intentionally scary-named so callers think twice before
    passing untrusted bytes to it.
    """
    warnings.warn(
        "Loading legacy pickle session — this is dangerous and should only be "
        "used for explicit migration.",
        RuntimeWarning,
        stacklevel=3,
    )
    return pickle.loads(data)  # noqa: S301


def _get_legacy_hmac_key() -> bytes | None:
    """Return the HMAC key for legacy pickle session verification.

    The key is read from the ``MUSE_LEGACY_HMAC_KEY`` environment variable
    or from the ``legacy_hmac_key`` config setting (loaded lazily).
    Returns ``None`` if neither is set.
    """
    # Try environment variable first
    env_key = os.environ.get("MUSE_LEGACY_HMAC_KEY")
    if env_key:
        return env_key.encode("utf-8")
    # Try config
    try:
        from code_muse.config import get_config_value

        key = get_config_value("legacy_hmac_key")
        if key:
            return key.encode("utf-8") if isinstance(key, str) else key
    except Exception:
        pass
    return None


def _verify_legacy_signature(raw: bytes, key: bytes) -> bytes:
    """Verify the HMAC-SHA256 signature on a legacy pickle session file.

    Legacy format: ``CPSESSION\\x01`` (12-byte magic) + 32-byte HMAC-SHA256
    signature + pickle payload.

    Args:
        raw: Full file contents.
        key: HMAC key used to verify the signature.

    Returns:
        The raw pickle payload (bytes after the signature).

    Raises:
        ValueError: If the signature is missing, malformed, or does not match.
    """
    if not raw.startswith(_LEGACY_SIGNED_HEADER):
        raise ValueError(
            f"File does not start with legacy session header {_LEGACY_SIGNED_HEADER!r}"
        )

    header_len = len(_LEGACY_SIGNED_HEADER)
    expected_min_len = header_len + _LEGACY_SIGNATURE_SIZE + 1
    if len(raw) < expected_min_len:
        raise ValueError(
            f"Legacy session file too short: {len(raw)} bytes, "
            f"expected at least {expected_min_len}"
        )

    stored_sig = raw[header_len : header_len + _LEGACY_SIGNATURE_SIZE]
    payload = raw[header_len + _LEGACY_SIGNATURE_SIZE :]

    # Compute expected HMAC-SHA256 of the payload
    expected_sig = hmac.new(key, payload, "sha256").digest()

    if not hmac.compare_digest(stored_sig, expected_sig):
        raise ValueError(
            "HMAC signature verification FAILED for legacy pickle session. "
            "The file may have been tampered with or was saved with a "
            "different key. Refusing to load."
        )

    return payload


def _extract_pickle_payload(raw: bytes) -> bytes:
    """Return the pickle payload from raw session file bytes, verifying HMAC.

    Legacy format was: header + 32-byte HMAC-SHA256 signature + pickle payload.

    If a legacy HMAC key is configured (via ``MUSE_LEGACY_HMAC_KEY`` env var
    or ``legacy_hmac_key`` config), the signature is cryptographically verified
    before the payload is returned.

    If no key is configured, the payload is returned without verification
    (backward compatibility for users who never set up signing).

    Args:
        raw: Raw file contents.

    Returns:
        The pickle payload bytes.

    Raises:
        ValueError: If signature verification is enabled and fails, or if
            the file format is invalid.
    """
    key = _get_legacy_hmac_key()
    if key is not None:
        return _verify_legacy_signature(raw, key)

    # No key configured — extract without verification (legacy behavior)
    if raw.startswith(_LEGACY_SIGNED_HEADER):
        offset = len(_LEGACY_SIGNED_HEADER) + _LEGACY_SIGNATURE_SIZE
        return raw[offset:]
    return raw


def _wrap_messages(messages: Any) -> dict[str, Any]:
    # Attempt pydantic-ai serialisation; fall back to raw for plain data.
    try:
        dumped = ModelMessagesTypeAdapter.dump_python(messages, mode="json")
    except Exception:
        dumped = messages
    return {
        "schema": _SCHEMA_VERSION,
        "format": _FORMAT,
        "messages": dumped,
    }


def _unwrap_messages(data: Any) -> Any:
    """Unwrap serialised session data back into message objects.

    When the data matches our JSON schema we validate through
    ``ModelMessagesTypeAdapter``.  When it doesn't (plain dicts,
    simple lists, etc.) we return the raw payload so callers that
    saved non-pydantic-ai histories still get their data back.
    """
    if not isinstance(data, dict):
        return data

    schema = data.get("schema")
    if schema != _SCHEMA_VERSION:
        # If the dict has a "messages" key, return the raw messages list
        # so that callers working with plain dict histories get their data.
        raw = data.get("messages")
        if isinstance(raw, list):
            return raw
        raise ValueError(f"Unknown session schema: {schema}")

    raw_messages = data.get("messages", [])
    if not isinstance(raw_messages, list):
        raise ValueError("Session 'messages' must be a list")

    # Try pydantic-ai validation; if it fails, return raw messages
    try:
        return ModelMessagesTypeAdapter.validate_python(raw_messages)
    except Exception:
        return raw_messages


def _is_binary_pickle(data: bytes) -> bool:
    """Heuristic: does *data* look like binary pickle rather than JSON text?"""
    # JSON text is UTF-8 decodable and starts with '{' or '['
    try:
        text = data.decode("utf-8")
        return not text.lstrip().startswith(("{", "["))
    except UnicodeDecodeError, ValueError:
        return True


@dataclass(slots=True)
class SessionPaths:
    """Paths for a single session.

    The ``pickle_path`` field is retained for backward compatibility with
    existing callers.  It now uses the ``.pkl`` extension for compat, but
    the file contents are JSON (same as the canonical ``.json`` file).
    """

    pickle_path: Path
    metadata_path: Path


@dataclass(slots=True)
class SessionMetadata:
    """Metadata describing a persisted session.

    The ``pickle_path`` field is retained for backward compatibility but
    now points to a ``.pkl`` file (containing JSON).
    """

    session_name: str
    timestamp: str
    message_count: int
    total_tokens: int
    pickle_path: Path
    metadata_path: Path
    auto_saved: bool = False

    def as_serialisable(self) -> dict[str, Any]:
        return {
            "session_name": self.session_name,
            "timestamp": self.timestamp,
            "message_count": self.message_count,
            "total_tokens": self.total_tokens,
            "file_path": str(self.pickle_path),
            "auto_saved": self.auto_saved,
        }


def ensure_directory(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def _canonical_json_path(base_dir: Path, session_name: str) -> Path:
    """Return the canonical JSON session path."""
    return base_dir / f"{session_name}.json"


def build_session_paths(base_dir: Path, session_name: str) -> SessionPaths:
    session_path = base_dir / f"{session_name}.pkl"
    metadata_path = base_dir / f"{session_name}_meta.json"
    return SessionPaths(pickle_path=session_path, metadata_path=metadata_path)


def _atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    """Write JSON data atomically to *path*."""
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    tmp.replace(path)


def _try_load_pkl(path: Path, *, allow_legacy: bool = False) -> Any:
    """Attempt to load a .pkl session file.

    Returns the loaded data or ``_UNABLE_TO_LOAD`` if the file cannot be
    loaded under the current security constraints.

    - JSON-format .pkl files (written by current save_session) are always
      loaded.
    - Binary pickle files (with or without the ``_LEGACY_SIGNED_HEADER``
      prefix) require ``allow_legacy=True``.
    - When ``allow_legacy=True`` and an HMAC key is configured, the legacy
      HMAC-SHA256 signature is **verified** before deserialization. If
      verification fails, the file is rejected with a clear error.
    - When ``allow_legacy=True`` and no HMAC key is configured, the payload
      is extracted without verification and a warning is emitted (legacy
      behavior).
    """
    raw = path.read_bytes()

    # Try JSON first (current save_session writes JSON to .pkl)
    if not _is_binary_pickle(raw):
        try:
            data = json.loads(raw)
            return _unwrap_messages(data)
        except json.JSONDecodeError:
            pass

    # Binary pickle — only with explicit legacy flag
    if allow_legacy:
        if _get_legacy_hmac_key() is None:
            warnings.warn(
                "Loading legacy pickle session WITHOUT HMAC verification. "
                "Set MUSE_LEGACY_HMAC_KEY or legacy_hmac_key config to "
                "enable cryptographic signature verification.",
                RuntimeWarning,
                stacklevel=3,
            )
        pickle_data = _extract_pickle_payload(raw)
        return _unsafe_pickle_loads_for_explicit_legacy_migration_only(pickle_data)

    return _UNABLE_TO_LOAD


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

    # Dirty-flag check: skip disk writes if the session data is unchanged
    hash_key = (str(base_dir), session_name)
    current_hash = _hash_session_data(session_data)
    if current_hash is not None and _LAST_SAVED_HASHES.get(hash_key) == current_hash:
        total_tokens = sum(token_estimator(message) for message in history)
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

    total_tokens = sum(token_estimator(message) for message in history)
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
            data = json.load(f)
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
                data = json.loads(await meta_file.read())
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
    try:
        from code_muse.config import set_current_autosave_from_session_name

        set_current_autosave_from_session_name(chosen_name)
    except Exception:
        pass

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
