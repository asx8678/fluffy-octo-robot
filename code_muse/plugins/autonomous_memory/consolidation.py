"""Stub consolidation engine for the Autonomous Memory Pipeline.

Combines per-session extractions into a project-level markdown memory file.
Future iterations will drive this via a consolidation LLM agent.
"""

import logging
from pathlib import Path

from .extraction import ExtractionResult

logger = logging.getLogger(__name__)


def consolidate_memories(extractions: list[ExtractionResult], project_dir: Path) -> str:
    """Combine extraction results into a single markdown document.

    This is a stub: it simply concatenates raw memory blocks with simple
    deduplication. A future consolidation agent will synthesise these into
    coherent project knowledge.
    """
    if not extractions:
        return "# Project Memory\n\nNo sessions extracted yet.\n"

    lines: list[str] = [
        "# Project Memory",
        "",
        f"Generated from {len(extractions)} sessions.",
        "",
    ]

    seen: set[str] = set()
    for ex in extractions:
        block = ex.raw_memory.strip()
        if block in seen:
            continue
        seen.add(block)
        lines.append(f"### {ex.session_path}")
        lines.append(f"*Synopsis: {ex.synopsis}*")
        lines.append(f"*Extracted at: {ex.extracted_at}*")
        lines.append("")
        lines.append(block)
        lines.append("")

    return "\n".join(lines)


def write_memory_files(consolidated_md: str, memory_dir: Path) -> tuple[Path, Path]:
    """Write the consolidated memory and a truncated summary to disk.

    Returns ``(memory_path, summary_path)``.
    """
    memory_dir.mkdir(parents=True, exist_ok=True)

    memory_path = memory_dir / "MEMORY.md"
    summary_path = memory_dir / "memory_summary.md"

    memory_path.write_text(consolidated_md, encoding="utf-8")

    summary = _truncate_to_words(consolidated_md, max_words=500)
    summary_path.write_text(summary, encoding="utf-8")

    logger.info(f"Wrote memory files to {memory_dir}")
    return memory_path, summary_path


def _truncate_to_words(text: str, max_words: int = 500) -> str:
    """Truncate markdown to approximately ``max_words`` words.

    Tries to end on a paragraph boundary for readability.
    """
    words = text.split()
    if len(words) <= max_words:
        return text

    # Truncate to max_words, then try to find the nearest paragraph break
    truncated = " ".join(words[:max_words])
    last_break = truncated.rfind("\n\n")
    if last_break > max_words * 0.5:
        truncated = truncated[:last_break]

    return truncated.strip() + "\n\n*(truncated)*\n"
