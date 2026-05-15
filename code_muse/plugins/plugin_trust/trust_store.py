"""Plugin trust storage — manages trust database for user plugins."""

import hashlib
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# XDG state directory for private trust storage
import os
from datetime import UTC

from code_muse.secret_storage import (
    atomic_write_private_json,
    ensure_private_dir,
    warn_or_fix_private_file_mode,
)

_TRUST_DIR = (
    Path(
        os.environ.get(
            "XDG_STATE_HOME",
            Path.home() / ".local" / "state",
        )
    )
    / "muse"
    / "plugin_trust"
)

_TRUST_FILE = _TRUST_DIR / "plugin_trust.json"


def _load_trust_db() -> dict[str, dict]:
    """Load the plugin trust database from private storage."""
    import orjson as json

    ensure_private_dir(_TRUST_DIR)
    if not _TRUST_FILE.exists():
        return {}
    warn_or_fix_private_file_mode(_TRUST_FILE)
    with open(_TRUST_FILE, encoding="utf-8") as f:
        data = json.loads(f.read())
        if not isinstance(data, dict):
            logger.warning("Plugin trust database is malformed; resetting")
            return {}
        return data


def _save_trust_db(db: dict[str, dict]) -> None:
    """Save the plugin trust database to private storage."""
    ensure_private_dir(_TRUST_DIR)
    atomic_write_private_json(_TRUST_FILE, db)


def compute_plugin_hash(plugin_dir: Path) -> str:
    """Compute a SHA-256 hash of the plugin's entry point files.

    Hashes register_callbacks.py (or __init__.py) along with any .py files
    in the plugin directory for deterministic trust verification.
    """
    hasher = hashlib.sha256()

    # Find the entry point file
    callbacks_file = plugin_dir / "register_callbacks.py"
    init_file = plugin_dir / "__init__.py"

    entry_point = callbacks_file if callbacks_file.exists() else init_file

    if entry_point.exists():
        hasher.update(entry_point.read_bytes())

    # Hash all .py files in the plugin directory for content verification
    for py_file in sorted(plugin_dir.rglob("*.py")):
        if py_file.is_file():
            hasher.update(py_file.read_bytes())

    return hasher.hexdigest()


def is_plugin_trusted(plugin_name: str, content_hash: str) -> bool:
    """Check whether a user plugin is explicitly trusted."""
    db = _load_trust_db()
    entry = db.get(plugin_name)
    if entry is None:
        return False
    # If the hash has changed, trust is revoked
    if entry.get("hash") != content_hash:
        return False
    return entry.get("trusted", False)


def record_plugin_trust(plugin_name: str, content_hash: str, path: str) -> None:
    """Explicitly mark a user plugin as trusted."""
    from datetime import datetime

    db = _load_trust_db()
    db[plugin_name] = {
        "hash": content_hash,
        "path": path,
        "trusted": True,
        "timestamp": datetime.now(UTC).isoformat(),
    }
    _save_trust_db(db)
    logger.info("Plugin trusted: %s (hash=%s...)", plugin_name, content_hash[:12])


def revoke_plugin_trust(plugin_name: str) -> None:
    """Revoke trust for a user plugin regardless of content hash."""
    db = _load_trust_db()
    if plugin_name in db:
        del db[plugin_name]
        _save_trust_db(db)
        logger.info("Plugin trust revoked: %s", plugin_name)
