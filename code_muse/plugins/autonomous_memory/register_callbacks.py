"""Autonomous Memory Pipeline — callback registrations.

Wires the memory pipeline into the Fast Puppy runtime:
- ``startup``: log memory status on boot
- ``get_model_system_prompt``: inject memory into system prompts
- ``custom_command`` / ``custom_command_help``: ``/memory`` slash command
"""

import logging
from datetime import UTC
from typing import Any

from code_muse.callbacks import register_callback
from code_muse.messaging import emit_error

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------


def _setup_cython_hooks() -> None:
    """Enable pyximport so .pyx modules compile on-the-fly.

    Status is reported centrally by the core startup callback runner.
    """
    try:
        import pyximport

        pyximport.install(language_level=3, build_in_temp=True, inplace=True)
    except Exception:
        pass  # core will report Cython status


def _on_startup() -> None:
    """Attempt to load memory injection (non-blocking)."""
    try:
        from .memory_injection import load_memory_injection

        memory = load_memory_injection()
        if memory:
            logger.info("Memory injection available on startup")
        else:
            logger.debug("No fresh memory injection found")
    except Exception as exc:
        logger.warning(f"Memory startup check failed: {exc}")


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------


def _inject_memory_into_prompt(
    model_name: str, default_system_prompt: str, user_prompt: str
) -> dict[str, Any | None]:
    """Callback to inject memory into system prompt.

    Returns ``None`` when no memory is available so the prompt is unchanged.
    Returns ``handled: False`` so other prompt-augmenting callbacks can
    also run (e.g. the agent_skills plugin).
    """
    try:
        from .memory_injection import load_memory_injection

        memory_text = load_memory_injection()
        if not memory_text:
            return None

        enhanced = f"{default_system_prompt}\n\n## Memory Guidance\n\n"
        enhanced += (
            "The following is accumulated project knowledge from past sessions.\n"
            "Treat it as heuristic context, not authoritative fact. Always prefer\n"
            "current repo evidence over conflicting memory. Cite the memory path\n"
            "(MEMORY.md) when you use remembered information.\n\n"
        )
        enhanced += memory_text

        return {
            "instructions": enhanced,
            "user_prompt": user_prompt,
            "handled": False,
        }
    except Exception as exc:
        logger.warning(f"Memory prompt injection failed: {exc}")
        return None


# ---------------------------------------------------------------------------
# /memory slash command
# ---------------------------------------------------------------------------


def _memory_command_help() -> list[tuple[str, str]]:
    return [
        ("memory", "Show memory status"),
        ("memory extract", "Trigger extraction now"),
        ("memory forget", "Clear all memory files"),
    ]


def _handle_memory_command(command: str, name: str) -> bool | str | None:
    """Handle ``/memory`` and its subcommands."""
    if name != "memory":
        return None

    parts = command.strip().split()
    subcommand = parts[1] if len(parts) > 1 else ""

    if subcommand in ("", "status"):
        return _memory_status()

    if subcommand == "extract":
        return _memory_extract()

    if subcommand == "forget":
        return _memory_forget()

    emit_error(f"Unknown /memory subcommand: {subcommand}")
    return True


def _memory_status() -> str:
    """Display current memory status."""
    try:
        from .session_scanner import (
            get_memory_dir,
            get_project_hash,
            get_sessions_dir,
            scan_eligible_sessions,
        )

        sessions_dir = get_sessions_dir()
        state_file = sessions_dir / ".memory_state.json"
        eligible = scan_eligible_sessions(sessions_dir, state_file)

        project_hash = get_project_hash()
        memory_dir = get_memory_dir(project_hash)
        memory_path = memory_dir / "MEMORY.md"
        summary_path = memory_dir / "memory_summary.md"

        lines: list[str] = ["=== Memory Status ==="]
        lines.append(f"Eligible sessions: {len(eligible)}")
        lines.append(f"Memory dir: {memory_dir}")
        lines.append(f"MEMORY.md exists: {memory_path.exists()}")
        lines.append(f"memory_summary.md exists: {summary_path.exists()}")

        if summary_path.exists():
            mtime = summary_path.stat().st_mtime
            from datetime import datetime

            dt = datetime.fromtimestamp(mtime, tz=UTC)
            lines.append(f"Last extraction: {dt.isoformat()}")

        return "\n".join(lines)
    except Exception as exc:
        logger.error(f"Memory status failed: {exc}")
        return f"Memory status error: {exc}"


def _memory_extract() -> str:
    """Run the full extraction pipeline immediately."""
    try:
        from .consolidation import consolidate_memories, write_memory_files
        from .extraction import extract_session_knowledge
        from .lease_lock import acquire_memory_lease, release_lease
        from .secret_scanner import scan_for_secrets
        from .session_scanner import (
            get_memory_dir,
            get_project_hash,
            get_sessions_dir,
            mark_session_processed,
            scan_eligible_sessions,
        )

        sessions_dir = get_sessions_dir()
        state_file = sessions_dir / ".memory_state.json"
        eligible = scan_eligible_sessions(sessions_dir, state_file)

        if not eligible:
            return "No eligible sessions found for extraction."

        project_hash = get_project_hash()
        memory_dir = get_memory_dir(project_hash)

        lease = acquire_memory_lease(memory_dir)
        if lease is None:
            return "Memory pipeline is already running (lease held). Try again later."

        try:
            extractions = []
            for info in eligible:
                result = extract_session_knowledge(info.path)
                if result:
                    extractions.append(result)
                    mark_session_processed(state_file, str(info.path))

            if not extractions:
                return "Extraction produced no results."

            consolidated = consolidate_memories(extractions, sessions_dir)

            # Safety scan before writing
            secrets = scan_for_secrets(consolidated)
            if secrets:
                secret_names = ", ".join(sorted({s.pattern_name for s in secrets}))
                from code_muse.messaging import emit_error

                emit_error(
                    f"Secrets detected in consolidated memory — write BLOCKED: {secret_names}"
                )
                logger.warning(
                    "Secret write blocked: %s",
                    secret_names,
                )
                return f"Memory extraction BLOCKED: secrets detected ({secret_names}). Remove secrets and retry."

            memory_path, summary_path = write_memory_files(consolidated, memory_dir)
            return (
                f"Extraction complete: {len(extractions)} sessions, "
                f"MEMORY.md → {memory_path}, summary → {summary_path}"
            )
        finally:
            release_lease(lease)
    except Exception as exc:
        logger.error(f"Memory extraction failed: {exc}")
        return f"Extraction error: {exc}"


def _memory_forget() -> str:
    """Remove all memory files for the current project."""
    try:
        from .session_scanner import get_memory_dir, get_project_hash

        project_hash = get_project_hash()
        memory_dir = get_memory_dir(project_hash)

        if not memory_dir.exists():
            return "No memory files to forget."

        deleted: list[str] = []
        for child in memory_dir.iterdir():
            try:
                if child.is_file():
                    child.unlink()
                    deleted.append(child.name)
                elif child.is_dir():
                    # Don't recursively delete; just report
                    deleted.append(f"{child.name}/ (skipped)")
            except OSError as exc:
                logger.warning(f"Could not delete {child}: {exc}")

        return f"Forgot memory files: {', '.join(deleted) or 'none'}"
    except Exception as exc:
        logger.error(f"Memory forget failed: {exc}")
        return f"Forget error: {exc}"


# ---------------------------------------------------------------------------
# Register callbacks
# ---------------------------------------------------------------------------

register_callback("startup", _setup_cython_hooks)
register_callback("startup", _on_startup)
register_callback("get_model_system_prompt", _inject_memory_into_prompt)
register_callback("custom_command_help", _memory_command_help)
register_callback("custom_command", _handle_memory_command)

logger.info("Autonomous Memory Pipeline plugin loaded")
