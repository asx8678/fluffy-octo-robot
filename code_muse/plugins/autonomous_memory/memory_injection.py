"""Memory injection for the Autonomous Memory Pipeline.

Loads the current project's memory summary (if fresh) and appends it to
system prompts for heuristic context.
"""

import logging
import os
import time

from .session_scanner import get_memory_dir, get_project_hash

logger = logging.getLogger(__name__)

FRESHNESS_DAYS = 7


def load_memory_injection(cwd: str | None = None) -> str | None:
    """Load the memory summary for the current project if it is fresh.

    Returns the memory text, or ``None`` if the file is missing or stale.
    """
    try:
        cwd = cwd or os.getcwd()
        project_hash = get_project_hash(cwd)
        memory_dir = get_memory_dir(project_hash)
        summary_path = memory_dir / "memory_summary.md"

        if not summary_path.exists():
            return None

        mtime = summary_path.stat().st_mtime
        age_days = (time.time() - mtime) / 86_400
        if age_days > FRESHNESS_DAYS:
            logger.debug(f"Memory summary stale ({age_days:.1f} days old)")
            return None

        text = summary_path.read_text(encoding="utf-8")
        logger.info(f"Loaded memory injection from {summary_path}")
        return text
    except Exception as exc:
        logger.warning(f"Failed to load memory injection: {exc}")
        return None


def inject_into_system_prompt(base_prompt: str, memory_text: str) -> str:
    """Append a memory section to ``base_prompt``.

    Returns the combined prompt string.
    """
    section = (
        "\n\n## Memory Guidance\n\n"
        "The following is accumulated project knowledge from past sessions.\n"
        "Treat it as heuristic context, not authoritative fact. Always prefer\n"
        "current repo evidence over conflicting memory. Cite the memory path\n"
        "(MEMORY.md) when you use remembered information.\n\n"
        f"{memory_text}"
    )
    return base_prompt + section
