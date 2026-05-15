"""AST-based relevance engine for the Context-Aware Code Reader.

Extracts meaningful sections (imports, functions, classes) from source code
and scores them against the current task focus areas.

Design goals (from epic):
- Always include ALL imports (they are small and critical).
- High-relevance sections → full body.
- Low-relevance sections → signature only (via existing compression where possible).
- Graceful fallback to full file if parsing fails.
- 1-based line numbers matching `read_file` convention exactly.
"""

import ast
import logging
from pathlib import Path

from rapidfuzz import fuzz

from code_muse.plugins.context_aware_reader.config import get_auto_extensions
from code_muse.plugins.context_aware_reader.models import CodeSection, RelevanceResult

logger = logging.getLogger(__name__)


def _score_text(text: str, focus_areas: list[str] | None) -> float:
    """Simple but effective relevance score using rapidfuzz."""
    if not focus_areas:
        return 0.5
    text_lower = text.lower()
    scores = [
        fuzz.partial_ratio(area.lower(), text_lower) / 100.0 for area in focus_areas
    ]
    return max(scores) if scores else 0.3


def _extract_python_sections(
    source: str, focus_areas: list[str] | None
) -> list[CodeSection]:
    """Parse Python using the stdlib ast module (very reliable)."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []

    lines = source.splitlines(keepends=True)
    sections: list[CodeSection] = []

    # 1. Always capture all top-level imports
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            start = node.lineno
            end = getattr(node, "end_lineno", node.lineno)
            content = "".join(lines[start - 1 : end])
            sections.append(
                CodeSection(
                    start_line=start,
                    end_line=end,
                    kind="import",
                    name=None,
                    score=1.0,  # Imports are always high value
                    content=content,
                )
            )

    # 2. Functions and classes
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            start = node.lineno
            end = getattr(node, "end_lineno", node.lineno)
            name = node.name
            # Get the signature line(s) + first few lines for scoring
            header = ast.get_source_segment(source, node) or ""
            score = _score_text(header + " " + name, focus_areas)
            # Boost top-level definitions
            if (
                isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                and node.col_offset == 0
            ):
                score = max(score, 0.65)

            content = "".join(lines[start - 1 : end])
            kind = "class" if isinstance(node, ast.ClassDef) else "function"
            sections.append(
                CodeSection(
                    start_line=start,
                    end_line=end,
                    kind=kind,
                    name=name,
                    score=score,
                    content=content,
                )
            )

    return sections


def _heuristic_sections(
    source: str, focus_areas: list[str] | None, language: str
) -> list[CodeSection]:
    """Very lightweight heuristic for non-Python languages (JS/TS/Go/Rust etc)."""
    lines = source.splitlines(keepends=True)
    sections: list[CodeSection] = []
    total = len(lines)

    # Capture import/require/use statements
    import_keywords = ("import ", "from ", "require(", "#include", "use ", "mod ")
    for i, line in enumerate(lines, 1):
        stripped = line.strip().lower()
        if any(stripped.startswith(k) for k in import_keywords):
            sections.append(
                CodeSection(
                    start_line=i,
                    end_line=i,
                    kind="import",
                    name=None,
                    score=1.0,
                    content=line,
                )
            )

    # Very rough function/class detection for common languages
    func_prefixes = (
        "def ",
        "function ",
        "async def ",
        "fn ",
        "func ",
        "public ",
        "private ",
    )
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        lower = stripped.lower()
        if (
            any(lower.startswith(p) for p in func_prefixes)
            or "{" in stripped
            and any(k in lower for k in ("func", "fn", "def"))
        ):
            # Take a small window around it
            end = min(i + 8, total)
            content = "".join(lines[i - 1 : end])
            score = _score_text(content, focus_areas)
            sections.append(
                CodeSection(
                    start_line=i,
                    end_line=end,
                    kind="function",
                    name=None,
                    score=score,
                    content=content,
                )
            )

    return sections


def analyze_relevance(
    file_path: str | Path,
    content: str,
    focus_areas: list[str] | None = None,
) -> RelevanceResult:
    """Main entry point. Returns scored sections for a file."""
    path = Path(file_path)
    ext = path.suffix.lower()
    total_lines = len(content.splitlines())

    if not content.strip():
        return RelevanceResult(
            file_path=str(path), total_lines=0, sections=[], language="empty"
        )

    language = None
    sections: list[CodeSection] = []
    used_fallback = False

    supported = get_auto_extensions()

    if ext in supported:
        if ext == ".py":
            language = "python"
            sections = _extract_python_sections(content, focus_areas)
        else:
            language = ext.lstrip(".")
            sections = _heuristic_sections(content, focus_areas, language)

    if not sections:
        # Fallback: return the whole file as one "other" section so caller can decide
        used_fallback = True
        sections = [
            CodeSection(
                start_line=1,
                end_line=total_lines or 1,
                kind="other",
                name=path.name,
                score=0.4,
                content=content,
            )
        ]

    # De-duplicate overlapping sections (keep highest score)
    sections.sort(key=lambda s: (s.start_line, -s.score))
    merged: list[CodeSection] = []
    for sec in sections:
        if not merged or sec.start_line > merged[-1].end_line:
            merged.append(sec)
        else:
            # overlap — keep the higher scoring one
            if sec.score > merged[-1].score:
                merged[-1] = sec

    return RelevanceResult(
        file_path=str(path),
        total_lines=total_lines,
        sections=merged,
        used_fallback=used_fallback,
        language=language,
    )
