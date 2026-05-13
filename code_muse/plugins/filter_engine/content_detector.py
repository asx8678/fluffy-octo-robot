"""Content type detector for shell command output.

Sniffs stdout to classify output as JSON, diff, log, HTML, code, or unknown.
Uses fast heuristics — no LLM calls.
"""

import enum
import json
import re
from typing import ClassVar


class ContentType(enum.Enum):
    """Output content types."""

    JSON = "json"
    DIFF = "diff"
    LOG = "log"
    HTML = "html"
    CODE = "code"
    SEARCH = "search"
    UNKNOWN = "unknown"


class ContentTypeDetector:
    """Detect content type from shell command stdout."""

    # Pre-compiled patterns
    DIFF_HEADER: ClassVar[re.Pattern] = re.compile(
        r"^@@\s+-(\d+),?\d*\s+\+(\d+),?\d*\s+@@", re.MULTILINE
    )
    LOG_PATTERNS: ClassVar[list[re.Pattern]] = [
        re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}"),  # ISO timestamp
        re.compile(r"^\d{2}:\d{2}:\d{2}\.\d{3}"),  # HH:MM:SS.mmm
        re.compile(r"^\[?\d{4}-\d{2}-\d{2}\]?"),  # [YYYY-MM-DD]
        re.compile(r"^\w+\s+\d+\s+\d{2}:\d{2}:\d{2}"),  # syslog style
        re.compile(r"^(ERROR|WARN|INFO|DEBUG|TRACE|FATAL)\b", re.IGNORECASE),
    ]
    # Single combined log pattern for efficient matching
    LOG_COMBINED: ClassVar[re.Pattern] = re.compile(
        "|".join(
            [
                r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}",  # ISO timestamp
                r"^\d{2}:\d{2}:\d{2}\.\d{3}",  # HH:MM:SS.mmm
                r"^\[?\d{4}-\d{2}-\d{2}\]?",  # [YYYY-MM-DD] (brackets optional)
                r"^\w+\s+\d+\s+\d{2}:\d{2}:\d{2}",  # syslog style
                r"^(ERROR|WARN|INFO|DEBUG|TRACE|FATAL)\b",  # log levels
            ]
        ),
        re.IGNORECASE,
    )
    HTML_PATTERNS: ClassVar[list[re.Pattern]] = [
        re.compile(r"<html[\s>]", re.IGNORECASE),
        re.compile(r"<!DOCTYPE\s+html", re.IGNORECASE),
        re.compile(r"<head[\s>]", re.IGNORECASE),
        re.compile(r"<body[\s>]", re.IGNORECASE),
        re.compile(r"<div[\s>]", re.IGNORECASE),
        re.compile(
            r"</?(?:html|head|body|div|span|p|a|table|tr|td)[\s>]", re.IGNORECASE
        ),
    ]
    SEARCH_PATTERNS: ClassVar[list[re.Pattern]] = [
        re.compile(r"^Found\s+\d+\s+results?", re.IGNORECASE),
        re.compile(r"^\d+\s+matches?", re.IGNORECASE),
        re.compile(r"^---\s+search\s+results?\s+---", re.IGNORECASE),
        re.compile(r"^\d+:\d+:.*\x1b", re.MULTILINE),  # grep -n output
    ]

    @classmethod
    def detect(cls, stdout: str) -> ContentType:
        """Detect content type from stdout string.

        Args:
            stdout: The full stdout from the shell command.

        Returns:
            ContentType enum value.
        """
        if not stdout or not stdout.strip():
            return ContentType.UNKNOWN

        text = stdout.strip()

        # 1. JSON detection — try to parse
        if cls._is_json(text):
            return ContentType.JSON

        # 2. Diff detection — unified diff headers
        if cls.DIFF_HEADER.search(text):
            return ContentType.DIFF

        # 3. Log detection — timestamp patterns or log levels
        if cls._is_log(text):
            return ContentType.LOG

        # 4. HTML detection
        if cls._is_html(text):
            return ContentType.HTML

        # 5. Search results detection
        if cls._is_search(text):
            return ContentType.SEARCH

        # 6. Code detection — keyword density
        if cls._is_code(text):
            return ContentType.CODE

        return ContentType.UNKNOWN

    # ------------------------------------------------------------------
    # Private heuristics
    # ------------------------------------------------------------------

    @classmethod
    def _is_json(cls, text: str) -> bool:
        """Test if text is valid JSON (object or array)."""
        # Fast check: first non-whitespace char is { or [
        first = text.lstrip()[0] if text else ""
        if first not in ("{", "["):
            return False
        try:
            json.loads(text)
            return True
        except ValueError:
            return False

    @classmethod
    def _is_log_fast(cls, text: str) -> bool:
        """Test if text looks like log output using single combined pattern."""
        lines = text.splitlines()
        if not lines:
            return False
        log_lines = sum(1 for line in lines[:50] if cls.LOG_COMBINED.search(line))
        return log_lines > max(1, min(len(lines), 50) * 0.3)

    @classmethod
    def _is_log(cls, text: str) -> bool:
        """Test if text looks like log output.

        First tries the efficient single combined pattern.
        Falls back to per-pattern matching for edge cases.
        """
        if cls._is_log_fast(text):
            return True
        # Fallback: keep the original multi-pattern approach for safety
        lines = text.splitlines()
        if not lines:
            return False
        log_lines = 0
        for line in lines[:50]:
            if any(pat.search(line) for pat in cls.LOG_PATTERNS):
                log_lines += 1
        return log_lines > max(1, min(len(lines), 50) * 0.3)

    @classmethod
    def _is_html(cls, text: str) -> bool:
        """Test if text looks like HTML."""
        return any(pat.search(text[:2000]) for pat in cls.HTML_PATTERNS)

    @classmethod
    def _is_code(cls, text: str) -> bool:
        """Test if text looks like source code by structural detection."""
        lines = text.splitlines()
        if not lines:
            return False

        # Structural signals — check first 100 non-empty lines
        significant_lines = 0
        code_signals = 0
        brace_depth = 0
        indent_depth = 0

        for line in lines[:100]:
            stripped = line.strip()
            if not stripped or stripped.startswith(("#", "//", "/*", "*")):
                continue

            significant_lines += 1
            if significant_lines > 30:
                break

            # Shebang detection
            if stripped.startswith("#!"):
                code_signals += 2
                continue

            # Leading structural keywords at start of line
            if re.match(
                r"^\s*(def |class |function |fn |const |let |var "
                r"|import |from |package |export |interface |trait "
                r"|impl |public |private |protected |static )",
                line,
            ):
                code_signals += 2
                continue

            # Control flow at start of line
            if re.match(
                r"^\s*(if |for |while |try |catch |switch |return |elif|else:)",
                line,
            ):
                code_signals += 1
                continue

            # Track brace depth for C-family languages
            brace_depth += stripped.count("{") - stripped.count("}")

            # Track indentation (meaningful indentation = Python/Ruby/YAML)
            leading_spaces = len(line) - len(line.lstrip())
            if leading_spaces > 0:
                indent_depth += 1

        # Signal: non-trivial brace nesting
        if brace_depth > 2:
            code_signals += 2

        # Signal: consistent indentation
        if indent_depth > significant_lines * 0.3:
            code_signals += 1

        # Combined signal: structural detection
        return code_signals >= 3

    @classmethod
    def _is_search(cls, text: str) -> bool:
        """Test if text looks like search results (grep/rg/find output)."""
        for pat in cls.SEARCH_PATTERNS:
            if pat.search(text[:2000]):
                return True
        # Also check for filename:line: pattern (grep -n)
        return re.search(r"^\S+\.\w+:\d+:", text[:2000], re.MULTILINE) is not None
