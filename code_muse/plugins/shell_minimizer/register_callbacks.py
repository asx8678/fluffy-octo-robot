"""Shell Minimizer plugin — callback registration.

Registers:
    - ``run_shell_command`` callback that intercepts shell commands,
      matches them against built-in (and user) pipeline definitions,
      executes them, applies the minimizer pipeline, and returns the
      compressed result to the LLM.
    - ``/minimizer`` custom command to show stats, toggle verbosity,
      and list active filters.
    - ``startup`` hook for logging and built-in filter loading.
    - ``custom_command_help`` entries for slash-command discovery.

NOTE: We use the ``run_shell_command`` hook (not ``post_tool_call``)
because ``post_tool_call`` fires *after* the tool result is already
returned to the LLM, whereas ``run_shell_command`` lets us intercept
and modify the result *before* it reaches the model.
"""

import logging
from pathlib import Path
from typing import Any

from code_muse.callbacks import register_callback
from code_muse.messaging import emit_info
from code_muse.plugins.filter_engine.verbosity import get_verbosity
from code_muse.tools.command_runner import ShellCommandOutput, _execute_shell_command
from code_muse.tools.subagent_context import is_subagent

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

_pipelines: list = []  # list[CompiledPipeline], loaded lazily
_stats: dict[str, int] = {"intercepted": 0, "bytes_saved": 0, "pipelines": 0}
_disabled: bool = False


def _is_disabled() -> bool:
    """Check whether the minimizer has been toggled off via ``/minimizer off``."""
    return _disabled


# ---------------------------------------------------------------------------
# Pipeline loading
# ---------------------------------------------------------------------------


def _load_builtin_pipelines() -> list:
    """Load and compile pipelines from the built-in TOML file."""
    from code_muse.plugins.shell_minimizer.pipeline import parse_pipeline_toml

    builtin_path = Path(__file__).parent / "builtin_filters.toml"
    if not builtin_path.exists():
        logger.warning("builtin_filters.toml not found at %s", builtin_path)
        return []

    try:
        raw = builtin_path.read_text(encoding="utf-8")
        return parse_pipeline_toml(raw, str(builtin_path))
    except Exception as exc:
        logger.error("Failed to load builtin filters: %s", exc)
        return []


def _get_pipelines() -> list:
    """Return the compiled pipeline list, loading on first access."""
    global _pipelines
    if not _pipelines:
        _pipelines = _load_builtin_pipelines()
        _stats["pipelines"] = len(_pipelines)
        logger.debug("Loaded %d minimizer pipelines", len(_pipelines))
    return _pipelines


# ---------------------------------------------------------------------------
# Command matching
# ---------------------------------------------------------------------------


def _find_pipeline(command: str) -> Any | None:
    """Return the first pipeline whose match patterns accept *command*.

    Returns ``None`` when no pipeline matches.
    """
    from code_muse.plugins.shell_minimizer.pipeline import CompiledPipeline

    for pipeline in _get_pipelines():
        if isinstance(pipeline, CompiledPipeline) and pipeline.matches_program(command):
            return pipeline
    return None


# ---------------------------------------------------------------------------
# run_shell_command callback
# ---------------------------------------------------------------------------


async def _minimizer_callback(
    context: Any,
    command: str,
    cwd: str | None = None,
    timeout: int = 60,
) -> dict[str, Any] | None:
    """Intercept shell commands, apply minimizer pipeline, return compressed output.

    Args:
        context: pydantic-ai RunContext (unused).
        command: The shell command string.
        cwd: Working directory.
        timeout: Timeout in seconds.

    Returns:
        ``{"pre_executed": True, "output": ShellCommandOutput(...)}`` when a
        pipeline handles the command, or ``None`` to let normal execution
        or downstream callbacks (filter_engine, build_filter, etc.) proceed.
    """
    if _is_disabled():
        return None

    pipeline = _find_pipeline(command)
    if pipeline is None:
        return None  # No matching pipeline; let others handle

    verbosity = get_verbosity()
    if verbosity.value >= 4:  # RAW: no filtering
        return None

    try:
        # Execute the command (sub-agents run silently)
        silent = is_subagent()
        group_id = f"shell_minim_{id(command)}"

        output = await _execute_shell_command(
            command=command,
            cwd=cwd,
            timeout=timeout,
            group_id=group_id,
            silent=silent,
        )

        # Combine stdout + stderr for pipeline processing
        raw_text = (output.stdout or "") + (
            "\n" + output.stderr if output.stderr else ""
        )
        exit_code = output.exit_code or 0

        # Apply pipeline
        compressed = pipeline.apply(raw_text, exit_code)

        # Update stats
        _stats["intercepted"] += 1
        raw_len = len(raw_text.encode("utf-8"))
        comp_len = len(compressed.encode("utf-8"))
        _stats["bytes_saved"] += max(0, raw_len - comp_len)

        # Build filtered ShellCommandOutput
        # Preserve original exit_code and success flag
        filtered = ShellCommandOutput(
            success=output.success,
            command=command,
            stdout=compressed,
            stderr="",  # stderr is folded into stdout after compression
            exit_code=exit_code,
            execution_time=output.execution_time,
        )

        # Track token savings (best-effort, never blocks)
        try:
            from code_muse.plugins.token_tracking.record import record_command

            pipeline_name = getattr(pipeline, "name", "unknown")
            record_command(
                command=command,
                raw_stdout=output.stdout or "",
                raw_stderr=output.stderr or "",
                compressed_stdout=compressed,
                compressed_stderr="",
                category=f"minim_{pipeline_name}",
                strategy="shell_minimizer",
                exit_code=exit_code,
            )
        except Exception:
            pass

        return {"pre_executed": True, "output": filtered}

    except Exception:
        logger.exception("Shell Minimizer: pipeline failed for %r", command)
        return None  # Fallback to raw execution


# ---------------------------------------------------------------------------
# /minimizer custom command
# ---------------------------------------------------------------------------


def _minimizer_help() -> list[tuple[str, str]]:
    return [
        ("/minimizer", "Show minimizer status and stats"),
        ("/minimizer off", "Disable output minimisation"),
        ("/minimizer on", "Re-enable output minimisation"),
        ("/minimizer list", "List all active pipeline filters"),
    ]


def _handle_minimizer_command(command: str, name: str) -> bool | str | None:
    """Handle ``/minimizer`` and its subcommands."""
    global _disabled

    if name != "minimizer":
        return None

    tokens = command.strip().split()
    sub = tokens[1] if len(tokens) > 1 else "status"

    if sub == "off":
        _disabled = True
        emit_info("🔇 Shell Minimizer disabled. Output will pass through unfiltered.")
        return True

    if sub == "on":
        _disabled = False
        emit_info("🔊 Shell Minimizer re-enabled.")
        return True

    if sub == "list":
        lines = ["**Active Minimizer Pipelines:**"]
        for p in _get_pipelines():
            name = getattr(p, "name", "?")
            cmd = getattr(p, "match_command", None)
            subc = getattr(p, "match_subcommand", None)
            cmd_pat = cmd.pattern if cmd else "*"
            sub_pat = subc.pattern if subc else "*"
            lines.append(f"  • **{name}** → `{cmd_pat}` `{sub_pat}`")
        return "\n".join(lines)

    # Default: status
    status_lines = [
        f"🔧 **Shell Minimizer** — active ({_stats['pipelines']} pipelines loaded)",
        f"  Commands intercepted: {_stats['intercepted']}",
        f"  Bytes saved: {_stats['bytes_saved']:,}",
        f"  Status: {'🟡 DISABLED' if _disabled else '🟢 enabled'}",
        "",
        "Use `/minimizer list` to see all pipelines.",
        "Use `/minimizer off` / `/minimizer on` to toggle.",
    ]
    return "\n".join(status_lines)


# ---------------------------------------------------------------------------
# Startup hook
# ---------------------------------------------------------------------------


def _on_startup() -> None:
    """Log plugin status and pre-load built-in pipelines."""
    try:
        n = len(_get_pipelines())
        logger.info("Shell Minimizer loaded with %d built-in pipelines", n)
    except Exception as exc:
        logger.warning("Shell Minimizer startup check failed: %s", exc)


# ---------------------------------------------------------------------------
# Register all callbacks
# ---------------------------------------------------------------------------

# Priority: intended 0 (runs third, after policy_engine/shell_safety=50).
# Compresses shell output when no other handler matches.
register_callback("run_shell_command", _minimizer_callback, priority=-10)
register_callback("custom_command", _handle_minimizer_command)
register_callback("custom_command_help", _minimizer_help)
register_callback("startup", _on_startup)

logger.debug("Shell Minimizer plugin callbacks registered")
