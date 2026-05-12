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
    CODE_KEYWORDS: ClassVar[set[str]] = {
        "def",
        "class",
        "import",
        "from",
        "function",
        "const",
        "let",
        "var",
        "return",
        "if",
        "else",
        "for",
        "while",
        "try",
        "except",
        "catch",
        "public",
        "private",
        "protected",
        "static",
        "void",
        "int",
        "string",
        "package",
        "export",
        "require",
        "module",
    }
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
    def _is_log(cls, text: str) -> bool:
        """Test if text looks like log output."""
        lines = text.splitlines()
        if not lines:
            return False
        # Count lines matching log patterns
        log_lines = 0
        for line in lines[:50]:  # sample first 50 lines
            for pat in cls.LOG_PATTERNS:
                if pat.search(line):
                    log_lines += 1
                    break
        # If > 30% of sampled lines match, treat as log
        return log_lines > max(1, min(len(lines), 50) * 0.3)

    @classmethod
    def _is_html(cls, text: str) -> bool:
        """Test if text looks like HTML."""
        return any(pat.search(text[:2000]) for pat in cls.HTML_PATTERNS)

    @classmethod
    def _is_code(cls, text: str) -> bool:
        """Test if text looks like source code by keyword density."""
        lines = text.splitlines()
        if not lines:
            return False
        words = text.lower().split()
        if not words:
            return False
        code_words = sum(1 for w in words[:500] if w in cls.CODE_KEYWORDS)
        # If > 5% of words are code keywords, treat as code
        return code_words > max(3, min(len(words), 500) * 0.05)

    @classmethod
    def _is_search(cls, text: str) -> bool:
        """Test if text looks like search results (grep/rg/find output)."""
        for pat in cls.SEARCH_PATTERNS:
            if pat.search(text[:2000]):
                return True
        # Also check for filename:line: pattern (grep -n)
        return re.search(r"^\S+\.\w+:\d+:", text[:2000], re.MULTILINE) is not None
