"""Plugin loading system.

Built-in plugins (under code_muse/plugins/) load unconditionally.
User plugins (under ~/.muse/plugins/) load automatically without trust checks.
No sys.path insertion — user plugins are loaded via importlib with
unique module names to prevent stdlib/project shadowing.
"""

import concurrent.futures
import importlib
import importlib.util
import logging
import re
import sys
from pathlib import Path

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
        logger.error("Unexpected error loading built-in plugin %s: %s", plugin_name, e)
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
        item
        for item in plugins_dir.iterdir()
        if item.is_dir() and not item.name.startswith("_")
    ]
    if not plugin_dirs:
        return []

    loaded: list[str] = []
    # FREE-THREADED: ThreadPoolExecutor is compatible with free-threaded Python 3.14.
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        futures = {
            executor.submit(
                _import_single_builtin_plugin, plugins_dir, item, failed_names
            ): item
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
# User plugin loading (no trust checks)
# ---------------------------------------------------------------------------

_SAFE_NAME_RE = re.compile(r"^[a-zA-Z0-9_-]+$")


def _load_single_user_plugin(
    plugin_dir: Path,
    plugin_name: str,
    user_plugins_dir: Path,
    failed_names: list[str] | None = None,
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

    # Build unique module name to avoid import shadowing
    module_name = f"code_muse_user_plugin_{plugin_name}"

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
    insertion.

    Returns list of successfully loaded plugin names.
    """
    loaded = []

    if not user_plugins_dir.exists():
        return loaded

    if not user_plugins_dir.is_dir():
        logger.warning("User plugins path is not a directory: %s", user_plugins_dir)
        return loaded

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

        plugin_items.append((item, plugin_name))

    if not plugin_items:
        return loaded

    # FREE-THREADED: ThreadPoolExecutor is compatible with free-threaded Python 3.14.
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        futures = {
            executor.submit(
                _load_single_user_plugin, item, name, user_plugins_dir, failed_names
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
                logger.error(
                    "Unexpected thread error loading user plugin '%s': %s",
                    plugin_name,
                    e,
                )
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
    from code_muse.secret_storage import ensure_private_dir

    ensure_private_dir(USER_PLUGINS_DIR)
    return USER_PLUGINS_DIR
