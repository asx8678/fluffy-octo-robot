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
import os
import pickle
import warnings
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import orjson
import orjson as json
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
        return hashlib.sha256(json.dumps(data, option=orjson.OPT_SORT_KEYS)).hexdigest()
    except (TypeError, ValueError):
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
    import code_muse.config.parser as _parser

    key = _parser.get_value("legacy_hmac_key")
    if key:
        return key.encode("utf-8") if isinstance(key, str) else key
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
    except (UnicodeDecodeError, ValueError):
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
        f.write(json.dumps(data, option=orjson.OPT_INDENT_2).decode())
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
