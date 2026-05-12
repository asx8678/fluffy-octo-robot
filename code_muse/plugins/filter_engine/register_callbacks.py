"""Filter Engine plugin for Muse — callback registration.

Registers:
    - ``run_shell_command`` callback that intercepts shell commands
    - ``/init`` custom command for one-command project setup
    - Startup hook for tee-file cleanup
"""

import logging
import tempfile
import time
from pathlib import Path
from typing import Any

from code_muse.callbacks import register_callback
from code_muse.messaging import emit_info, emit_success, emit_warning

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Cython JIT hooks — safe fallback to pure Python
# ---------------------------------------------------------------------------


def _setup_cython_hooks() -> None:
    """Enable pyximport so .pyx modules compile on-the-fly.

    Falls back gracefully when Cython is missing or compilation fails.
    """
    try:
        import pyximport

        pyximport.install(
            language_level=3,
            build_in_temp=True,
            inplace=True,
        )
        import code_muse

        if code_muse.CYTHON_ENABLED:
            emit_success(
                f"✅ Cython enabled — {code_muse.PYX_MODULE_COUNT} modules compiled"
            )
        else:
            emit_warning("⚠️ Cython not available — running in pure Python mode")
    except ImportError:
        emit_warning("⚠️ Cython not available — running in pure Python mode")
    except Exception:  # noqa: BLE001
        emit_warning("⚠️ Cython not available — running in pure Python mode")


# ---------------------------------------------------------------------------
# Startup hook — tee file cleanup
# ---------------------------------------------------------------------------


def _on_startup() -> None:
    """Delete tee files older than 24 hours on startup."""
    try:
        tee_dir = Path(tempfile.gettempdir()) / "muse_tee"
        if tee_dir.exists():
            now = time.time()
            for f in tee_dir.iterdir():
                if f.is_file() and now - f.stat().st_mtime > 86400:
                    f.unlink(missing_ok=True)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Run-shell-command callback
# ---------------------------------------------------------------------------


async def filter_engine_callback(
    context: Any,
    command: str,
    cwd: str | None = None,
    timeout: int = 60,
) -> dict[str, Any] | None:
    """Run-shell-command callback for the filter engine.

    Args:
        context: The pydantic-ai RunContext (unused).
        command: The shell command to potentially intercept.
        cwd: Working directory for the command.
        timeout: Timeout in seconds.

    Returns:
        ``{"pre_executed": True, "output": ShellCommandOutput(...)}`` when the
        filter engine handles the command, or ``None`` to let normal execution
        proceed.
    """
    from code_muse.plugins.filter_engine.dispatcher import FilterDispatcher

    dispatcher = FilterDispatcher.get_instance()
    return await dispatcher.handle(context, command, cwd, timeout)


# ---------------------------------------------------------------------------
# /init custom command
# ---------------------------------------------------------------------------


_INIT_MARKDOWN = """# Fast-Puppy Token Saving

This project uses Fast-Puppy to compress shell command output, reducing token usage by 60-90%.

## Enabled Strategies
- Git output compression (status, log, diff)
- Test runner failure focus
- Lint output grouping
- Code-aware read filtering

## Configuration
See `~/.muse/config.toml` for global settings.

## Commands
Run `/tracking gain` to see token savings.
"""

_PROJECT_FILES = [
    "pyproject.toml",
    "package.json",
    "Cargo.toml",
    "go.mod",
    "Gemfile",
]


def _detect_project_type(cwd: Path) -> str | None:
    """Detect project type from known manifest files."""
    for manifest in _PROJECT_FILES:
        if (cwd / manifest).exists():
            return manifest
    return None


def _on_custom_command(command: str, name: str) -> bool | None:  # noqa: ARG001
    """Handle ``/init`` — one-command Fast-Puppy setup."""
    if name != "init":
        return None

    cwd = Path.cwd()
    manifest = _detect_project_type(cwd)

    md_path = cwd / "FAST_PUPPY.md"
    if md_path.exists():
        emit_info("FAST_PUPPY.md already exists — nothing to do.")
        return True

    md_path.write_text(_INIT_MARKDOWN, encoding="utf-8")
    if manifest:
        emit_success(
            f"✅ Fast-Puppy initialized. Detected {manifest}. "
            f"Created FAST_PUPPY.md. Filter engine is active."
        )
    else:
        emit_success(
            "✅ Fast-Puppy initialized. Created FAST_PUPPY.md. Filter engine is active."
        )
    return True


# ---------------------------------------------------------------------------
# Help entries
# ---------------------------------------------------------------------------


def _on_custom_command_help() -> list[tuple[str, str]]:
    return [
        ("/init", "Initialize Fast-Puppy in the current project"),
    ]


# ---------------------------------------------------------------------------
# Register all callbacks
# ---------------------------------------------------------------------------

register_callback("startup", _on_startup)
register_callback("startup", _setup_cython_hooks)
# Priority: runs first (before policy_engine=50). Performs content-type detection and routing.
register_callback("run_shell_command", filter_engine_callback, priority=10)
register_callback("custom_command", _on_custom_command)
register_callback("custom_command_help", _on_custom_command_help)

logger.debug("Filter Engine plugin callbacks registered")
