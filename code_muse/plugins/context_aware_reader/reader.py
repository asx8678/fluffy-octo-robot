"""Reader output assembly for the Context-Aware Code Reader.

Takes the scored sections from the relevance engine and produces a
beautiful, line-numbered, token-efficient `ReadFileOutput` that matches
the contract of the built-in `read_file` tool as closely as possible.
"""

import logging
from pathlib import Path

from code_muse.plugins.context_aware_reader.ast_relevance import analyze_relevance
from code_muse.plugins.context_aware_reader.config import get_max_relevant_lines
from code_muse.plugins.context_aware_reader.models import RelevanceResult
from code_muse.tools.file_operations import ReadFileOutput
from code_muse.tools.path_policy import Operation, check_path_allowed

logger = logging.getLogger(__name__)


def _estimate_tokens(text: str) -> int:
    """Rough token estimate (matches the spirit of the core estimator)."""
    return max(1, len(text) // 4)


def _format_section(sec, total_lines: int) -> str:
    header = f"--- Section: {sec.name or sec.kind} (lines {sec.start_line}-{sec.end_line}) ---"
    body = ""
    for i, line in enumerate(sec.content.splitlines(), sec.start_line):
        body += f"[line {i:4d}] {line}\n"
    return f"{header}\n{body}"


def read_relevant_code(
    file_path: str,
    focus_areas: list[str] | None = None,
    max_lines: int | None = None,
) -> ReadFileOutput:
    """
    Primary public function for the `read_relevant_code` tool.

    Returns the same `ReadFileOutput` shape as the built-in read_file tool.
    """
    path = Path(file_path)

    # Enforce path policy exactly like read_file
    policy = check_path_allowed(str(path), Operation.READ)
    if policy.denied:
        return ReadFileOutput(
            content=None,
            num_tokens=0,
            error=policy.reason or "Access denied by path policy",
        )

    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return ReadFileOutput(content=None, num_tokens=0, error=str(e))

    total_lines = len(content.splitlines())
    if total_lines == 0:
        return ReadFileOutput(content="", num_tokens=0)

    # Run the relevance engine
    result: RelevanceResult = analyze_relevance(path, content, focus_areas)

    max_lines = max_lines or get_max_relevant_lines()

    # Separate imports (always shown) from scored sections
    imports = [s for s in result.sections if s.kind == "import"]
    others = [s for s in result.sections if s.kind != "import"]

    # Sort others by score desc, then take until we hit the soft cap
    others.sort(key=lambda s: s.score, reverse=True)

    selected: list = list(imports)
    used_lines = sum(s.end_line - s.start_line + 1 for s in selected)

    for sec in others:
        sec_lines = sec.end_line - sec.start_line + 1
        if used_lines + sec_lines <= max_lines or not selected:
            selected.append(sec)
            used_lines += sec_lines
        else:
            # For low-relevance sections we still want to show they exist
            # (the issue asks for "Omitted X lines" markers)
            pass

    # Build the beautiful output
    lines_out: list[str] = []
    lines_out.append(f"--- File: {path} ({total_lines} lines total) ---")

    if focus_areas:
        lines_out.append(f"--- Focus: {', '.join(focus_areas)} ---")

    shown_ranges = []
    for sec in sorted(selected, key=lambda s: s.start_line):
        lines_out.append(_format_section(sec, total_lines))
        shown_ranges.append((sec.start_line, sec.end_line))

    # Add omission summary if we dropped content
    if len(selected) < len(result.sections):
        omitted = total_lines - used_lines
        lines_out.append(f"\n--- Omitted {omitted} lines of lower-relevance code ---")

    final_content = "\n".join(lines_out)
    num_tokens = _estimate_tokens(final_content)

    return ReadFileOutput(
        content=final_content,
        num_tokens=num_tokens,
        error=None,
    )
