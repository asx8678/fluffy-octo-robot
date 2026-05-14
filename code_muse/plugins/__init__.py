"""Plugin loading with trust model for user plugins.

Built-in plugins (under code_muse/plugins/) load unconditionally.
User plugins (under ~/.muse/plugins/) require explicit trust
recorded in a manifest keyed by content hash; fail closed by default.
No sys.path insertion — user plugins are loaded via importlib with
unique module names to prevent stdlib/project shadowing.
"""

import concurrent.futures
import contextlib
import hashlib
import importlib
import importlib.util
import orjson as json
import logging
import os
import re
import sys
from pathlib import Path

from code_muse.secret_storage import atomic_write_private_json, ensure_private_dir

logger = logging.getLogger(__name__)

# User plugins directory
USER_PLUGINS_DIR = Path.home() / ".muse" / "plugins"

# Track if plugins have already been loaded to prevent duplicate registration
_PLUGINS_LOADED = False


def _clean_stale_pycache(root_dir: Path) -> None:
    """Remove stale __pycache__ directories to prevent import ghosts.

    Deletes any __pycache__ directory whose containing .py file no longer
    exists.  This prevents stale bytecode from old package names (e.g.
    after a rename) from causing ``No module named X`` errors.
    """
    import shutil

    for pycache_dir in list(root_dir.rglob("__pycache__")):
        if not pycache_dir.is_dir():
            continue
        # Check if any .py file in parent directory still exists
        parent = pycache_dir.parent
        has_py_files = any(parent.glob("*.py"))
        if not has_py_files:
            # Parent dir has no .py files anymore — likely a removed module
            try:
                shutil.rmtree(pycache_dir)
                logger.debug("Cleaned stale __pycache__: %s", pycache_dir)
            except OSError:
                pass


# ---------------------------------------------------------------------------
# Trust manifest helpers
# ---------------------------------------------------------------------------

# Env var / monkeypatch-friendly override for trust manifest path.
# Set MUSE_PLUGIN_TRUST_MANIFEST to a file path to redirect the DB.
_TRUST_MANIFEST_ENV = "MUSE_PLUGIN_TRUST_MANIFEST"

# Safe plugin name pattern: only alphanumeric + underscore + hyphen
_SAFE_NAME_RE = re.compile(r"^[a-zA-Z0-9_-]+$")

# Max SKILL.md content size (bytes) before we refuse to read
_MAX_SKILL_MD_BYTES = 256 * 1024  # 256 KiB

# Cap for skill content injected into model context (chars)
_SKILL_CONTEXT_CAP = 64_000  # ~64k chars


def _default_trust_manifest_path() -> Path:
    """Return default path for the plugin trust manifest."""
    return Path.home() / ".muse" / "plugin_trust.json"


def get_trust_manifest_path() -> Path:
    """Return the trust manifest path (env-override aware)."""
    env_val = os.environ.get(_TRUST_MANIFEST_ENV)
    if env_val:
        return Path(env_val)
    return _default_trust_manifest_path()


def _load_trust_manifest() -> dict:
    """Load the trust manifest from disk. Returns {} on any error."""
    path = get_trust_manifest_path()
    if not path.exists():
        return {}
    try:
        text = path.read_text(encoding="utf-8")
        data = orjson.loads(text)
        if isinstance(data, dict):
            return data
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Failed to read plugin trust manifest at %s: %s", path, exc)
    return {}


def _save_trust_manifest(manifest: dict) -> None:
    """Persist the trust manifest to disk atomically with private perms."""
    path = get_trust_manifest_path()
    try:
        ensure_private_dir(path.parent)
        atomic_write_private_json(path, manifest)
    except OSError as exc:
        logger.warning("Failed to save plugin trust manifest: %s", exc)


# Cache: resolved-dir-string -> (mtime_sum, total_size, hex_digest)
# Avoids re-reading every .py file when contents have not changed.
_plugin_hash_cache: dict[str, tuple[int, int, str]] = {}


def compute_plugin_hash(plugin_dir: Path) -> str:
    """Compute a SHA-256 hash over all .py files in a plugin directory.

    Hashes register_callbacks.py, __init__.py, and every other .py file
    found recursively under *plugin_dir*. Files are sorted by relative
    path for deterministic ordering. The hash covers file *contents*, not
    just file names.

    A lightweight cache keyed by ``(mtime_sum, total_size)`` avoids the
    expensive SHA-256 recomputation when files have not changed since the
    last call.

    Returns the hex digest string.
    """
    cache_key = str(plugin_dir.resolve())

    # --- First pass: collect files + lightweight mtime/size fingerprint ---
    py_files: list[Path] = []
    mtime_sum = 0
    total_size = 0

    try:
        for child in sorted(plugin_dir.rglob("*.py")):
            # Skip hidden files / dirs
            if any(
                part.startswith(".") for part in child.relative_to(plugin_dir).parts
            ):
                continue
            # Skip symlink escapes
            try:
                child.resolve().relative_to(plugin_dir.resolve())
            except ValueError:
                continue
            py_files.append(child)
            try:
                stat = child.stat()
                mtime_sum += int(stat.st_mtime)
                total_size += stat.st_size
            except OSError:
                pass
    except OSError:
        pass

    # Cache hit — return previously computed digest
    cached = _plugin_hash_cache.get(cache_key)
    if cached is not None and cached[0] == mtime_sum and cached[1] == total_size:
        return cached[2]

    # --- Cache miss — full SHA-256 computation ---
    h = hashlib.sha256()
    for fpath in sorted(py_files):
        rel = fpath.relative_to(plugin_dir)
        h.update(str(rel).encode())
        h.update(b"\0")
        with contextlib.suppress(OSError):
            h.update(fpath.read_bytes())
        h.update(b"\0")

    digest = h.hexdigest()
    _plugin_hash_cache[cache_key] = (mtime_sum, total_size, digest)
    return digest


def is_plugin_trusted(plugin_name: str, content_hash: str) -> bool:
    """Check if a user plugin is trusted (manifest contains matching hash)."""
    manifest = _load_trust_manifest()
    entry = manifest.get(plugin_name)
    if not isinstance(entry, dict):
        return False
    return entry.get("hash") == content_hash


def record_plugin_trust(plugin_name: str, content_hash: str, plugin_dir: str) -> None:
    """Record trust for a user plugin in the manifest."""
    manifest = _load_trust_manifest()
    manifest[plugin_name] = {
        "hash": content_hash,
        "path": plugin_dir,
        "trusted_at": _utc_now_iso(),
    }
    _save_trust_manifest(manifest)


def revoke_plugin_trust(plugin_name: str) -> None:
    """Remove a plugin from the trust manifest."""
    manifest = _load_trust_manifest()
    manifest.pop(plugin_name, None)
    _save_trust_manifest(manifest)


def _utc_now_iso() -> str:
    """Return current UTC time as ISO string (no heavy deps)."""
    import datetime

    return datetime.datetime.now(datetime.UTC).isoformat()


# ---------------------------------------------------------------------------
# Symlink / hidden-directory safety checks
# ---------------------------------------------------------------------------


def _is_symlink_escape(child: Path, parent: Path) -> bool:
    """Return True if *child* resolves outside *parent* (symlink escape)."""
    try:
        child.resolve().relative_to(parent.resolve())
        return False
    except ValueError:
        return True


def _should_skip_entry(item: Path, parent: Path) -> bool:
    """Return True if *item* should be skipped during plugin/skill discovery.

    Skips:
    - hidden dirs (name starts with '.' or '_')
    - symlink escapes outside *parent*
    """
    if item.name.startswith(".") or item.name.startswith("_"):
        return True
    if _is_symlink_escape(item, parent):
        logger.warning(
            "Skipping %s: resolves outside parent directory (symlink escape)", item
        )
        return True
    return False


# ---------------------------------------------------------------------------
# Built-in plugin loading
# ---------------------------------------------------------------------------


def _import_single_builtin_plugin(
    plugins_dir: Path, item: Path, failed_names: list[str] | None = None
) -> str | None:
    """Import a single built-in plugin. Returns plugin name or None on failure."""
    if not item.is_dir() or item.name.startswith("_"):
        return None
    plugin_name = item.name
    callbacks_file = item / "register_callbacks.py"
    if not callbacks_file.exists():
        return None
    try:
        module_name = f"code_muse.plugins.{plugin_name}.register_callbacks"
        importlib.import_module(module_name)
        return plugin_name
    except ImportError as e:
        logger.warning(
            "Failed to import callbacks from built-in plugin %s: %s", plugin_name, e
        )
        if failed_names is not None:
            failed_names.append(plugin_name)
    except Exception as e:
        logger.error(
            "Unexpected error loading built-in plugin %s: %s", plugin_name, e
        )
        if failed_names is not None:
            failed_names.append(plugin_name)
    return None


def _load_builtin_plugins(
    plugins_dir: Path, failed_names: list[str] | None = None
) -> list[str]:
    """Load built-in plugins from the package plugins directory in parallel.

    Returns list of successfully loaded plugin names.
    """
    plugin_dirs = [
        item for item in plugins_dir.iterdir()
        if item.is_dir() and not item.name.startswith("_")
    ]
    if not plugin_dirs:
        return []

    loaded: list[str] = []
    # FREE-THREADED: ThreadPoolExecutor is compatible with free-threaded Python 3.14.
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        futures = {
            executor.submit(_import_single_builtin_plugin, plugins_dir, item, failed_names): item
            for item in plugin_dirs
        }
        for future in concurrent.futures.as_completed(futures):
            try:
                result = future.result()
                if result is not None:
                    loaded.append(result)
            except Exception as e:
                logger.error("Unexpected thread error loading plugin: %s", e)

    return loaded


# ---------------------------------------------------------------------------
# User plugin loading (trust-gated)
# ---------------------------------------------------------------------------


def _make_user_module_name(plugin_name: str, content_hash: str) -> str:
    """Build a unique, safe module name for a user plugin.

    Format: ``code_muse_user_plugin_{safe_name}_{hash_prefix}``
    The hash prefix (first 12 chars) avoids name collisions while keeping
    the module name readable.
    """
    safe = re.sub(r"[^a-zA-Z0-9_]", "_", plugin_name)
    return f"code_muse_user_plugin_{safe}_{content_hash[:12]}"


def _load_single_user_plugin(
    plugin_dir: Path,
    plugin_name: str,
    user_plugins_dir: Path,
    failed_names: list[str] | None = None,
    trust_plugin_set: set[str] | None = None,
) -> str | None:
    """Attempt to load a single user plugin directory.

    Returns the plugin name on success, None on failure/skip.
    """
    # Safety checks
    if _should_skip_entry(plugin_dir, user_plugins_dir):
        return None

    # Validate plugin name
    if not _SAFE_NAME_RE.match(plugin_name):
        logger.warning(
            "Skipping user plugin '%s': name contains unsafe characters", plugin_name
        )
        return None

    callbacks_file = plugin_dir / "register_callbacks.py"
    init_file = plugin_dir / "__init__.py"

    # Pick the file to load (prefer register_callbacks.py)
    load_file = None
    if callbacks_file.exists():
        if _is_symlink_escape(callbacks_file, plugin_dir):
            logger.warning(
                "Skipping user plugin '%s': register_callbacks.py is a symlink escape",
                plugin_name,
            )
            return None
        load_file = callbacks_file
    elif init_file.exists():
        if _is_symlink_escape(init_file, plugin_dir):
            logger.warning(
                "Skipping user plugin '%s': __init__.py is a symlink escape",
                plugin_name,
            )
            return None
        load_file = init_file
    else:
        # No entry point file
        return None

    # Compute content hash for trust check
    content_hash = compute_plugin_hash(plugin_dir)

    # Auto-trust if named in MUSE_TRUST_PLUGIN env var
    if (
        trust_plugin_set
        and plugin_name in trust_plugin_set
        and not is_plugin_trusted(plugin_name, content_hash)
    ):
        record_plugin_trust(plugin_name, content_hash, str(plugin_dir))

    # Fail closed: untrusted plugins are NOT imported
    if not is_plugin_trusted(plugin_name, content_hash):
        logger.warning(
            "User plugin '%s' is not trusted (hash: %s…). "
            "To trust it, run: /plugin trust %s  "
            "or set MUSE_TRUST_PLUGIN=%s  "
            "or set MUSE_TRUST_ALL_USER_PLUGINS=1 (dangerous).",
            plugin_name,
            content_hash[:12],
            plugin_name,
            plugin_name,
        )
        return None

    # Build unique module name to avoid import shadowing
    module_name = _make_user_module_name(plugin_name, content_hash)

    try:
        spec = importlib.util.spec_from_file_location(module_name, load_file)
        if spec is None or spec.loader is None:
            logger.warning(
                "Could not create module spec for user plugin: %s", plugin_name
            )
            if failed_names is not None:
                failed_names.append(plugin_name)
            return None

        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        return plugin_name

    except ImportError as e:
        logger.warning(
            "Failed to import callbacks from user plugin %s: %s", plugin_name, e
        )
        if failed_names is not None:
            failed_names.append(plugin_name)
    except Exception as e:
        logger.error(
            "Unexpected error loading user plugin %s: %s", plugin_name, e, exc_info=True
        )
        if failed_names is not None:
            failed_names.append(plugin_name)

    return None


def _load_user_plugins(
    user_plugins_dir: Path, failed_names: list[str] | None = None
) -> list[str]:
    """Load user plugins from ~/.muse/plugins/ in parallel.

    Each plugin should be a directory containing a register_callbacks.py file.
    Plugins are loaded via importlib with unique module names — no sys.path
    insertion.  Untrusted plugins are skipped with a clear warning.

    Returns list of successfully loaded plugin names.
    """
    loaded = []

    if not user_plugins_dir.exists():
        return loaded

    if not user_plugins_dir.is_dir():
        logger.warning("User plugins path is not a directory: %s", user_plugins_dir)
        return loaded

    # Allow trusting all user plugins via env var (for development / CI)
    trust_all = os.environ.get("MUSE_TRUST_ALL_USER_PLUGINS", "") == "1"

    # Allow trusting specific plugins by name via env var
    trust_plugin_names = os.environ.get("MUSE_TRUST_PLUGIN", "")
    if trust_plugin_names:
        trust_plugin_set = {
            name.strip() for name in trust_plugin_names.split(",") if name.strip()
        }
    else:
        trust_plugin_set = set()

    plugin_items = []
    for item in user_plugins_dir.iterdir():
        if not item.is_dir():
            continue

        plugin_name = item.name

        # Safety checks
        if _should_skip_entry(item, user_plugins_dir):
            continue

        # Validate plugin name
        if not _SAFE_NAME_RE.match(plugin_name):
            logger.warning(
                "Skipping user plugin '%s': name contains unsafe characters",
                plugin_name,
            )
            continue

        # Dev override: auto-trust everything
        if trust_all:
            content_hash = compute_plugin_hash(item)
            if not is_plugin_trusted(plugin_name, content_hash):
                record_plugin_trust(plugin_name, content_hash, str(item))

        plugin_items.append((item, plugin_name))

    if not plugin_items:
        return loaded

    # FREE-THREADED: ThreadPoolExecutor is compatible with free-threaded Python 3.14.
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        futures = {
            executor.submit(
                _load_single_user_plugin, item, name, user_plugins_dir, failed_names, trust_plugin_set
            ): name
            for item, name in plugin_items
        }
        for future in concurrent.futures.as_completed(futures):
            try:
                result = future.result()
                if result is not None:
                    loaded.append(result)
            except Exception as e:
                plugin_name = futures[future]
                logger.error("Unexpected thread error loading user plugin '%s': %s", plugin_name, e)
                if failed_names is not None:
                    failed_names.append(plugin_name)

    return loaded


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def load_plugin_callbacks() -> dict[str, list[str]]:
    """Dynamically load register_callbacks.py from all plugin sources.

    Loads plugins from:
    1. Built-in plugins in the code_muse/plugins/ directory
    2. User plugins in ~/.muse/plugins/

    User plugins require trust (content-hash match in manifest).
    No sys.path manipulation is performed.

    All ``register_callback`` calls made by plugins during import are
    buffered and committed **atomically** — either every registration
    succeeds, or the entire batch is rolled back.

    Returns dict with 'builtin' and 'user' keys containing lists of loaded
    plugin names.

    NOTE: This function is idempotent - calling it multiple times will only
    load plugins once. Subsequent calls return empty lists.
    """
    # Clean stale __pycache__ to prevent import ghosts from renames
    _clean_stale_pycache(Path(__file__).parent)

    global _PLUGINS_LOADED

    # Prevent duplicate loading - plugins register callbacks at import time,
    # so re-importing would cause duplicate registrations
    if _PLUGINS_LOADED:
        logger.debug("Plugins already loaded, skipping duplicate load")
        return {"builtin": [], "user": []}

    from code_muse.callbacks import begin_deferred, commit_deferred, rollback_deferred

    plugins_dir = Path(__file__).parent
    builtin_failed: list[str] = []
    user_failed: list[str] = []

    # Begin deferred mode: all register_callback calls are buffered
    begin_deferred()

    try:
        result = {
            "builtin": _load_builtin_plugins(plugins_dir, builtin_failed),
            "user": _load_user_plugins(USER_PLUGINS_DIR, user_failed),
        }

        # Atomically commit all buffered registrations
        commit_deferred()
    except Exception:
        # Rollback any partial registrations on catastrophic failure
        rollback_deferred()
        raise

    total_loaded = len(result["builtin"]) + len(result["user"])
    total_failed = len(builtin_failed) + len(user_failed)
    if total_failed:
        all_failed = builtin_failed + user_failed
        names_str = ", ".join(all_failed)
        logger.warning("Plugin load failures: %s", names_str)
        from code_muse.messaging import emit_warning

        emit_warning(
            f"⚠️ {total_failed}/{total_loaded + total_failed} plugins failed to load"
        )

    _PLUGINS_LOADED = True
    logger.debug(
        "Loaded plugins: builtin=%s, user=%s", result["builtin"], result["user"]
    )

    return result


def reset_plugins_loaded_flag() -> None:
    """Reset the plugins loaded flag (primarily for testing)."""
    global _PLUGINS_LOADED
    _PLUGINS_LOADED = False


def get_user_plugins_dir() -> Path:
    """Return the path to the user plugins directory."""
    return USER_PLUGINS_DIR


def ensure_user_plugins_dir() -> Path:
    """Create the user plugins directory if it doesn't exist.

    Returns the path to the directory.
    """
    ensure_private_dir(USER_PLUGINS_DIR)
    return USER_PLUGINS_DIR
