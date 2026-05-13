# cython: language_level=3
"""Code / read compression strategies for the filter engine.

Handles comment stripping, tree compression, and smart truncation for
file-reading commands.
"""

import logging
import re
from collections import defaultdict
from typing import ClassVar

from code_muse.plugins.filter_engine.registry import get_registry

# AST-aware compression (Epic 021)
from code_muse.plugins.filter_engine.strategies.ast_compressor import (
    compress_ast_code,
)
from code_muse.plugins.filter_engine.strategies.ast_parser import (
    LanguageParser,
)
from code_muse.plugins.filter_engine.verbosity import VerbosityLevel
from code_muse.tools.command_runner import ShellCommandOutput

# ---------------------------------------------------------------------------
# Comment stripping helpers
# ---------------------------------------------------------------------------


class MinimalFilter:
    """Strip only comments, preserving docstrings that look like API docs."""

    # Language → (single_line_pattern, multi_line_pattern)
    # multi_line_pattern should capture the content between delimiters.
    PATTERNS: ClassVar[dict[str, tuple[str | None, str | None]]] = {
        "python": (
            r"#.*$",
            r'("""[\s\S]*?""")|(\'\'\'[\s\S]*?\'\'\')',
        ),
        "javascript": (
            r"//.*$",
            r"/\*[\s\S]*?\*/",
        ),
        "typescript": (
            r"//.*$",
            r"/\*[\s\S]*?\*/",
        ),
        "rust": (
            r"//.*$",
            r"/\*[\s\S]*?\*/",
        ),
        "go": (
            r"//.*$",
            r"/\*[\s\S]*?\*/",
        ),
        "java": (
            r"//.*$",
            r"/\*[\s\S]*?\*/",
        ),
        "cpp": (
            r"//.*$",
            r"/\*[\s\S]*?\*/",
        ),
        "ruby": (
            r"#.*$",
            r"=begin[\s\S]*?=end",
        ),
        "bash": (
            r"#.*$",
            None,
        ),
        "sql": (
            r"--.*$",
            r"/\*[\s\S]*?\*/",
        ),
    }

    @classmethod
    def strip_comments(cls, text: str, language: str = "python") -> str:
        """Remove single-line comments from *text* for *language*.

        Multi-line comments / docstrings are kept when they look like API
        documentation (contain words such as ``Args``, ``Returns``,
        ``Example``, ``Note``).

        Args:
            text: Source code text.
            language: Language key (see :attr:`PATTERNS`).

        Returns:
            Text with comments stripped.
        """
        single, multi = cls.PATTERNS.get(language, (None, None))
        result = text

        if single:
            result = re.sub(single, "", result, flags=re.MULTILINE)

        if multi:
            # Replace multi-line comments, but keep those that look like docs
            def _maybe_keep(match: re.Match[str]) -> str:
                block = match.group(0)
                doc_markers = (
                    "Args:",
                    "Returns:",
                    "Raises:",
                    "Example:",
                    "Note:",
                    "Notes:",
                )
                if any(marker in block for marker in doc_markers):
                    return block
                return ""

            result = re.sub(multi, _maybe_keep, result)

        return result


class AggressiveFilter:
    """Strip comments, docstrings, blank lines, and boilerplate."""

    PATTERNS: ClassVar[dict[str, tuple[str | None, str | None]]] = (
        MinimalFilter.PATTERNS
    )

    @classmethod
    def strip_comments(cls, text: str, language: str = "python") -> str:
        """Aggressively strip all comments and collapse blank lines.

        Args:
            text: Source code text.
            language: Language key.

        Returns:
            Compact text.
        """
        single, multi = cls.PATTERNS.get(language, (None, None))
        result = text

        if single:
            result = re.sub(single, "", result, flags=re.MULTILINE)

        if multi:
            result = re.sub(multi, "", result)

        # Collapse multiple blank lines into one
        result = re.sub(r"\n\s*\n+", "\n\n", result)

        return result.strip()


# ---------------------------------------------------------------------------
# Smart truncation
# ---------------------------------------------------------------------------


def _is_important_line(line: str) -> bool:
    """Heuristic: is this line important enough to preserve during truncation?"""
    stripped = line.strip()
    if not stripped:
        return False

    # Import lines
    if stripped.startswith("import ") or stripped.startswith("from "):
        return True

    # Function / class / method signatures
    if re.match(
        r"^(def |class |async def |fn |pub fn |func |function |method )", stripped
    ):
        return True

    # Decorators
    if stripped.startswith("@"):
        return True

    # Type signatures / interfaces
    if re.match(r"^(interface |type |struct |enum |trait |impl )", stripped):
        return True

    # Module / package declarations
    return bool(re.match(r"^(module |package |namespace )", stripped))


def _is_boilerplate(line: str) -> bool:
    """Heuristic: is this line boilerplate that can be dropped?"""
    stripped = line.strip()
    boilerplate_patterns = [
        r"^#\s*TODO",
        r"^#\s*FIXME",
        r"^#\s*HACK",
        r"^#\s*NOTE",
        r"^\s*\{\s*\}\s*$",  # empty blocks
        r"^\s*pass\s*$",  # Python pass
    ]
    return any(re.search(pattern, stripped) for pattern in boilerplate_patterns)


def smart_truncate(
    text: str,
    max_lines: int = 60,
    preserve_imports: bool = True,
    preserve_signatures: bool = True,
) -> str:
    """Truncate *text* to at most *max_lines* while preserving important lines.

    Important lines (imports, signatures, decorators) are always kept.
    Blank runs and boilerplate are collapsed or dropped.

    Args:
        text: The text to truncate.
        max_lines: Maximum number of lines to return.
        preserve_imports: Keep import lines even if they'd be dropped.
        preserve_signatures: Keep function/class signatures.

    Returns:
        Truncated text.
    """
    if not text:
        return ""

    lines = text.splitlines()
    if len(lines) <= max_lines:
        return text

    important: list[str] = []
    body: list[str] = []

    cdef str line
    cdef str stripped

    for line in lines:
        if _is_boilerplate(line):
            continue
        stripped = line.strip()
        if (preserve_imports and (stripped.startswith("import ") or stripped.startswith("from "))) or (
            preserve_signatures and _is_important_line(line)
        ):
            important.append(line)
        else:
            body.append(line)

    # Keep all important lines, then fill with body up to max_lines
    result = important[:max_lines]
    remaining = max_lines - len(result)
    if remaining > 0:
        result.extend(body[:remaining])

    if len(body) > remaining and remaining > 0:
        result.append(f"... ({len(body) - remaining} more lines)")

    return "\n".join(result)


# ---------------------------------------------------------------------------
# Tree / ls compression
# ---------------------------------------------------------------------------


def compress_tree(
    stdout: str,
    stderr: str,
    verbosity: VerbosityLevel,
) -> ShellCommandOutput:
    """Convert flat ``ls -R`` or ``tree`` output into a hierarchical summary.

    Args:
        stdout: Raw stdout.
        stderr: Raw stderr.
        verbosity: Current verbosity level.

    Returns:
        Compressed :class:`ShellCommandOutput`.
    """
    cdef list lines = stdout.splitlines()
    cdef str current_dir = "."
    cdef object dir_files = defaultdict(list)
    cdef object dir_dirs = defaultdict(list)

    cdef str line
    cdef str stripped
    cdef int file_count
    cdef int dir_count

    for line in lines:
        stripped = line.rstrip("\r")
        if stripped.endswith(":"):
            current_dir = stripped.rstrip(":")
            continue
        if not stripped or stripped.startswith("total "):
            continue

        # Heuristic: directories in ls -R are often marked with / or listed before files
        if stripped.endswith("/"):
            dir_dirs[current_dir].append(stripped)
        else:
            dir_files[current_dir].append(stripped)

    if not dir_files and not dir_dirs:
        return ShellCommandOutput(
            success=True,
            command="ls/tree",
            stdout=stdout.strip() or "Empty directory",
            stderr=stderr if verbosity >= VerbosityLevel.VERY_VERBOSE else None,
            exit_code=0,
            execution_time=None,
        )

    parts: list[str] = []
    cdef str directory
    cdef list files
    cdef list dirs

    for directory in sorted(set(list(dir_files.keys()) + list(dir_dirs.keys()))):
        files = dir_files.get(directory, [])
        dirs = dir_dirs.get(directory, [])
        file_count = len(files)
        dir_count = len(dirs)
        parts.append(f"{directory}: {file_count} files, {dir_count} dirs")
        if verbosity >= VerbosityLevel.VERBOSE:
            for d in dirs[:5]:
                parts.append(f"  /{d}")
            for f in files[:10]:
                parts.append(f"  {f}")
            if len(files) > 10:
                parts.append(f"  ... {len(files) - 10} more files")
            if len(dirs) > 5:
                parts.append(f"  ... {len(dirs) - 5} more dirs")

    return ShellCommandOutput(
        success=True,
        command="ls/tree",
        stdout="\n".join(parts),
        stderr=stderr if verbosity >= VerbosityLevel.VERY_VERBOSE else None,
        exit_code=0,
        execution_time=None,
    )


# ---------------------------------------------------------------------------
# Filename extraction helper
# ---------------------------------------------------------------------------


def _extract_code_filename(command: str) -> str | None:
    """Extract the last filename with an AST-supported extension from *command*."""
    pattern = r"[\w./-]+\.(?:py|pyi|js|mjs|cjs|jsx|ts|tsx|go|rs|java|c|h|cpp|cc|cxx|hpp|rb|sh|bash|sql)\b"
    matches = re.findall(pattern, command)
    return matches[-1] if matches else None


# ---------------------------------------------------------------------------
# Read command compression
# ---------------------------------------------------------------------------


def compress_read(
    command: str,
    stdout: str,
    stderr: str,
    exit_code: int,
    verbosity: VerbosityLevel,
) -> ShellCommandOutput:
    """Compress output from read commands (``cat``, ``head``, ``tail``, etc.).

    Applies AST-aware compression for supported languages, falling back to
    smart truncation and comment stripping for others.

    Args:
        command: The original read command.
        stdout: Raw stdout.
        stderr: Raw stderr.
        exit_code: Process exit code.
        verbosity: Current verbosity level.

    Returns:
        Compressed :class:`ShellCommandOutput`.
    """
    if verbosity >= VerbosityLevel.VERY_VERBOSE:
        return ShellCommandOutput(
            success=exit_code == 0,
            command=command,
            stdout=stdout,
            stderr=stderr,
            exit_code=exit_code,
            execution_time=None,
        )

    # Extract filename from command for AST language detection
    cdef str filename = _extract_code_filename(command) or ""

    # Try AST-aware compression when we have a supported filename
    if filename:
        try:
            compressed = compress_ast_code(
                stdout, filename=filename, verbosity=verbosity
            )
            return ShellCommandOutput(
                success=exit_code == 0,
                command=command,
                stdout=compressed,
                stderr=stderr if verbosity >= VerbosityLevel.VERY_VERBOSE else None,
                exit_code=exit_code,
                execution_time=None,
            )
        except Exception:
            logger = logging.getLogger(__name__)
            logger.debug("AST compression failed for %s, falling back", command)

    # Fallback: traditional comment stripping + smart truncation
    cdef str text = stdout
    cdef str language_str = "python"
    # Use LanguageParser for single-pass detection, then map to
    # MinimalFilter key — avoids duplicated extension maps.
    cdef object detected = LanguageParser.detect_language(stdout, filename or None)
    language_str = detected.to_filter_key()

    if verbosity <= VerbosityLevel.COMPACT:
        text = MinimalFilter.strip_comments(text, language_str)

    cdef int max_lines = 60
    if verbosity == VerbosityLevel.ULTRA_COMPACT:
        max_lines = 20
    elif verbosity == VerbosityLevel.COMPACT:
        max_lines = 60
    elif verbosity == VerbosityLevel.VERBOSE:
        max_lines = 120

    cdef str truncated = smart_truncate(text, max_lines=max_lines)

    return ShellCommandOutput(
        success=exit_code == 0,
        command=command,
        stdout=truncated,
        stderr=stderr if verbosity >= VerbosityLevel.VERY_VERBOSE else None,
        exit_code=exit_code,
        execution_time=None,
    )


# ---------------------------------------------------------------------------
# Code command compression (alias for read + ls/tree)
# ---------------------------------------------------------------------------


def compress_ls(
    command: str,
    stdout: str,
    stderr: str,
    exit_code: int,
    verbosity: VerbosityLevel,
) -> ShellCommandOutput:
    """Compress ``ls`` / ``tree`` output.

    Args:
        command: The original ls command.
        stdout: Raw stdout.
        stderr: Raw stderr.
        exit_code: Process exit code.
        verbosity: Current verbosity level.

    Returns:
        Compressed :class:`ShellCommandOutput`.
    """
    return compress_tree(stdout, stderr, verbosity)


def compress_code(
    command: str,
    stdout: str,
    stderr: str,
    exit_code: int,
    verbosity: VerbosityLevel,
) -> ShellCommandOutput | None:
    """Main dispatcher for code / read compression strategies.

    Args:
        command: The original command.
        stdout: Raw stdout.
        stderr: Raw stderr.
        exit_code: Process exit code.
        verbosity: Current verbosity level.

    Returns:
        A compressed :class:`ShellCommandOutput` or ``None``.
    """
    cdef str stripped = command.strip()
    cdef str text
    cdef str filename
    cdef bint ast_used = False
    cdef str language_str
    cdef int max_lines
    cdef str truncated

    # Read commands
    if re.search(r"\b(cat|head|tail|less|bat|nl)\b", stripped):
        return compress_read(command, stdout, stderr, exit_code, verbosity)

    # Directory listing
    if re.search(r"\b(ls|tree)\b", stripped):
        return compress_ls(command, stdout, stderr, exit_code, verbosity)

    # Generic code commands: apply smart truncate + minimal comment strip
    text = stdout
    filename = _extract_code_filename(command) or ""

    if filename:
        try:
            text = compress_ast_code(stdout, filename=filename, verbosity=verbosity)
            ast_used = True
        except Exception:
            logger = logging.getLogger(__name__)
            logger.debug("AST compression failed for %s, falling back", command)

    if not ast_used and verbosity <= VerbosityLevel.COMPACT:
        # Use LanguageParser for single-pass detection, then map to
        # MinimalFilter key — avoids duplicated extension maps.
        detected = LanguageParser.detect_language(text, filename or None)
        language_str = detected.to_filter_key()
        text = MinimalFilter.strip_comments(text, language_str)

    max_lines = 60
    if verbosity == VerbosityLevel.ULTRA_COMPACT:
        max_lines = 20
    elif verbosity == VerbosityLevel.VERBOSE:
        max_lines = 120

    truncated = smart_truncate(text, max_lines=max_lines)

    return ShellCommandOutput(
        success=exit_code == 0,
        command=command,
        stdout=truncated,
        stderr=stderr if verbosity >= VerbosityLevel.VERY_VERBOSE else None,
        exit_code=exit_code,
        execution_time=None,
    )


# ---------------------------------------------------------------------------
# Register with the strategy registry
# ---------------------------------------------------------------------------
get_registry().register("code", compress_code, priority=0)
get_registry().register("read", compress_code, priority=0)
