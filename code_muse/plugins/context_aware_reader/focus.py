"""Deterministic focus-area extraction from free-form task text.

Finds code-ish identifiers, dotted names, snake_case / camelCase /
PascalCase tokens, quoted symbols, error/test names, and de-duplicates
while preserving first-seen order.

Public API
----------
extract_focus_areas(task_text, max_areas=12) -> list[str]
"""

from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# Patterns (compiled once at import)
# ---------------------------------------------------------------------------

# Quoted symbols: `"foo_bar"`, `'MyClass'`, backtick-quoted ``thing``
_QUOTED_RE = re.compile(r"""["'`]([A-Za-z_][\w.-]*)["'`]""")

# Dotted names: `pkg.mod.Class`, `module.sub.func`
_DOTTED_RE = re.compile(r"\b([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+)\b")

# PascalCase: at least two segments; first can be an acronym like HTTP
# e.g. MyClass, HTTPServer, APIGateway
_PASCAL_RE = re.compile(r"\b([A-Z][A-Za-z]+(?:[A-Z][A-Za-z]+)+)\b")

# camelCase: lower then upper (myFunction, processData)
_CAMEL_RE = re.compile(r"\b([a-z][a-z0-9]+(?:[A-Z][a-z0-9]+)+)\b")

# snake_case: two or more underscore-separated lowercase words (my_func, test_thing)
_SNAKE_RE = re.compile(r"\b([a-z][a-z0-9]*(?:_[a-z0-9]+)+)\b")

# UPPER_SNAKE (constants / error codes): MY_CONST, ERR_TIMEOUT
_UPPER_SNAKE_RE = re.compile(r"\b([A-Z][A-Z0-9]*(?:_[A-Z0-9]+){1,})\b")

# Error / test / class suffix hints: "UserNotFoundError", "test_auth_flow"
_HINT_PREFIX_RE = re.compile(
    r"\b("
    r"(?:Error|Exception|Warning|Fault|Timeout|Failure)[A-Z]\w*"
    r"|test_\w+"
    r"|Test\w+"
    r"|describe_\w+"
    r"|it_\w+"
    r")\b"
)

# Common English / noise words to filter out
_NOISE: set[str] = {
    "the",
    "and",
    "for",
    "but",
    "not",
    "you",
    "are",
    "can",
    "has",
    "this",
    "that",
    "with",
    "from",
    "they",
    "been",
    "have",
    "will",
    "what",
    "when",
    "how",
    "why",
    "who",
    "all",
    "each",
    "than",
    "into",
    "over",
    "such",
    "only",
    "also",
    "just",
    "then",
    "some",
    "very",
    "even",
    "still",
    "since",
    "after",
    "before",
    "about",
    "other",
    "these",
    "those",
    "there",
    "where",
    "which",
    "while",
}


def extract_focus_areas(task_text: str, max_areas: int = 12) -> list[str]:
    """Extract likely code focus areas from free-form task text.

    Scans for identifiers, dotted names, quoted symbols, error/test
    names, and returns a de-duplicated list preserving first-seen order.

    Parameters
    ----------
    task_text:
        Free-form task description (e.g. "Fix the off-by-one error in
        UserService.validate_token when token_type is 'refresh'")
    max_areas:
        Maximum number of focus areas to return (prevents prompt bloat).

    Returns
    -------
    list[str]
        De-duplicated focus areas, up to *max_areas* items.
    """
    seen: set[str] = set()
    result: list[str] = []

    def _add(token: str) -> None:
        t = token.strip()
        if not t or len(t) < 2 or t in _NOISE or t.lower() in _NOISE:
            return
        if t not in seen:
            seen.add(t)
            result.append(t)

    # 1. Quoted symbols (highest signal)
    for m in _QUOTED_RE.finditer(task_text):
        _add(m.group(1))

    # 2. Dotted names
    for m in _DOTTED_RE.finditer(task_text):
        _add(m.group(1))

    # 3. Error / test / class hint prefixes
    for m in _HINT_PREFIX_RE.finditer(task_text):
        _add(m.group(1))

    # 4. PascalCase (multi-segment)
    for m in _PASCAL_RE.finditer(task_text):
        _add(m.group(1))

    # 5. UPPER_SNAKE (constants / error codes)
    for m in _UPPER_SNAKE_RE.finditer(task_text):
        _add(m.group(1))

    # 6. camelCase
    for m in _CAMEL_RE.finditer(task_text):
        _add(m.group(1))

    # 7. snake_case (multi-segment)
    for m in _SNAKE_RE.finditer(task_text):
        _add(m.group(1))

    return result[:max_areas]
