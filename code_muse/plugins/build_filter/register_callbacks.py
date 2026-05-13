"""Build Filter plugin for Muse — callback registration.

Registers:
    - ``run_shell_command`` callback that intercepts build commands
    - ``/build-filter`` custom command
"""

import logging
import re
from typing import Any

from code_muse.callbacks import register_callback
from code_muse.messaging import emit_info

# Import strategies so they self-register with the strategy registry
from code_muse.plugins.build_filter.strategies import build  # noqa: F401
from code_muse.plugins.filter_engine.verbosity import get_verbosity

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Build command classifier
# ---------------------------------------------------------------------------

BUILD_PATTERNS = [
    # make / cmake / ninja / msbuild
    r"^\s*make\b",
    r"^\s*cmake\b",
    r"^\s*ninja\b",
    r"^\s*msbuild\b",
    # Cargo
    r"^\s*cargo\s+build\b",
    r"^\s*cargo\s+run\b",
    # Go
    r"^\s*go\s+build\b",
    r"^\s*go\s+install\b",
    r"^\s*go\s+run\b",
    # Node
    r"^\s*npm\s+run\s+build\b",
    r"^\s*yarn\s+build\b",
    r"^\s*pnpm\s+build\b",
    r"^\s*npx\s+.*build\b",
    # Docker
    r"^\s*docker\s+build\b",
    r"^\s*docker\s+compose\s+build\b",
    r"^\s*docker-compose\s+build\b",
    # pip / uv
    r"^\s*pip\s+install\b",
    r"^\s*pip3\s+install\b",
    r"^\s*uv\s+pip\s+install\b",
    r"^\s*python\s+-m\s+pip\s+install\b",
    # Generic build tools
    r"^\s*\./configure\b",
    r"^\s*meson\b",
    r"^\s*bazel\s+build\b",
    r"^\s*gradle\s+build\b",
    r"^\s*mvn\s+compile\b",
    r"^\s*mvn\s+package\b",
]

_compiled_patterns = [re.compile(pattern) for pattern in BUILD_PATTERNS]


def _is_build_command(command: str) -> bool:
    """Check if a command matches any build pattern."""
    stripped = command.strip()
    return any(pattern.search(stripped) for pattern in _compiled_patterns)


# ---------------------------------------------------------------------------
# run_shell_command callback
# ---------------------------------------------------------------------------


async def build_filter_callback(
    context: Any,
    command: str,
    cwd: str | None = None,
    timeout: int = 60,
) -> dict[str, Any] | None:
    """Intercept build commands and compress their output.

    Returns ``{"pre_executed": True, "output": ShellCommandOutput(...)}`` for
    build commands, or ``None`` to passthrough to the filter engine.
    """
    if not _is_build_command(command):
        return None  # Let filter_engine handle it

    verbosity = get_verbosity()
    if verbosity.value >= 4:  # RAW: no filtering
        return None

    try:
        from code_muse.plugins.filter_engine.registry import get_registry
        from code_muse.tools.command_runner import _execute_shell_command
        from code_muse.tools.subagent_context import is_subagent

        silent = is_subagent()
        group_id = f"build_filter_{id(command)}"

        output = await _execute_shell_command(
            command=command,
            cwd=cwd,
            timeout=timeout,
            group_id=group_id,
            silent=silent,
        )

        strategy = get_registry().get_strategy("build")
        if strategy is None:
            return None  # Shouldn't happen since we registered it

        filtered = strategy(
            command,
            output.stdout or "",
            output.stderr or "",
            output.exit_code or 0,
            verbosity,
        )

        if filtered is None:
            return None

        # Track token savings (best-effort)
        try:
            from code_muse.plugins.token_tracking.record import record_command

            record_command(
                command=command,
                raw_stdout=output.stdout or "",
                raw_stderr=output.stderr or "",
                compressed_stdout=filtered.stdout or "",
                compressed_stderr=filtered.stderr or "",
                category="build",
                strategy="compress_build",
                exit_code=output.exit_code or 0,
            )
        except Exception:
            pass

        return {"pre_executed": True, "output": filtered}

    except Exception:
        logger.exception("BuildFilter: strategy failed for %r", command)
        return None  # Fallback to raw execution


# ---------------------------------------------------------------------------
# Help entries
# ---------------------------------------------------------------------------


def _on_custom_command_help() -> list[tuple[str, str]]:
    return [
        ("/build-filter status", "Show which build commands are being filtered"),
    ]


# ---------------------------------------------------------------------------
# /build-filter custom command
# ---------------------------------------------------------------------------


def _on_custom_command(command: str, name: str) -> bool | None:  # noqa: ARG001
    if name != "build-filter":
        return None

    tokens = command.strip().split()
    subcommand = tokens[1] if len(tokens) > 1 else "status"

    if subcommand == "status":
        emit_info(
            "Build Filter active — compressing output for:\n"
            "  • make / cmake / ninja / msbuild\n"
            "  • cargo build / cargo run\n"
            "  • go build / go install\n"
            "  • npm run build / yarn build / pnpm build\n"
            "  • docker build / docker-compose build\n"
            "  • pip install / uv pip install\n"
            "  • ./configure / meson / bazel build / gradle build / mvn\n"
            "\n"
            "Use -v / -vv for verbose output, -vvv for raw (unfiltered).\n"
            "Run /tracking gain to see token savings."
        )
        return True

    emit_info(
        f"Unknown /build-filter subcommand: {subcommand}\nTry /build-filter status"
    )
    return True


# ---------------------------------------------------------------------------
# Register all callbacks
# ---------------------------------------------------------------------------

# Priority: default 0 (runs after policy_engine/shell_safety=50, alongside shell_minimizer).
# Compresses build tool output (maven, gradle, cargo, go build, etc.).
register_callback("run_shell_command", build_filter_callback)
register_callback("custom_command", _on_custom_command)
register_callback("custom_command_help", _on_custom_command_help)

logger.debug("Build Filter plugin callbacks registered")
