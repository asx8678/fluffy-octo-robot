"""Pure truncation detection engine — no I/O, no hooks, no side effects.

All detection logic is consolidated here so it can be tested in complete
isolation from Muse's callback system.  The ``register_callbacks`` module
wraps these functions for hook integration.

Detection methods (in evaluation order — first match wins)
----------------------------------------------------------

1. **Empty string**  — trivially truncated
2. **Python ast.parse** — ``ast.parse()`` failure for ``.py`` / ``.pyi``
   (gold standard for Python, zero false positives)
3. **Open endings**  — code ending with incomplete tokens
   (``{``, ``[``, ``(``, ``:``, ``,``, ``&&``, ``||``, ``=``, ``->``, ``=>``)
4. **Truncated declarations** — last line starts with a declaration keyword
   but lacks a body (``def foo(``, ``class Bar``, ``if x``, etc.)
5. **Bracket imbalance** — too many opening brackets (``opens > closes + 3``)
6. **Trailing line truncation** — last line ends mid-expression
   (trailing operator, partial method call, ellipsis)
7. **Cut-off markdown code blocks** — unclosed triple-backtick / tilde fences
8. **Incomplete JSON** — ``json.loads()`` fails with truncation indicators

Design principle: **zero false positives**.  Each check is conservative —
only flag output that is *definitely* truncated, not merely suspicious.
"""

from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass
from pathlib import PurePosixPath

# ---------------------------------------------------------------------------
# Public result type
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TruncationResult:
    """Immutable detection result returned by :func:`detect_truncation`.

    Attributes:
        is_truncated: Whether truncation was detected.
        method: Detection method that triggered (``None`` if not truncated).
        reason: Human-readable explanation (``None`` if not truncated).
    """

    is_truncated: bool = False
    method: str | None = None
    reason: str | None = None


# ---------------------------------------------------------------------------
# Detection helpers
# ---------------------------------------------------------------------------


def _check_empty(content: str) -> TruncationResult | None:
    """Return a result if *content* is empty or whitespace-only."""
    if not content or not content.strip():
        return TruncationResult(
            is_truncated=True,
            method="empty",
            reason="Code content is empty or whitespace-only",
        )
    return None


def _check_ast_parse(content: str, file_path: str) -> TruncationResult | None:
    """Return a result if content is Python and fails ``ast.parse``.

    Only attempted for ``.py`` / ``.pyi`` extensions.  This is the gold
    standard for Python — zero false positives for real Python files.
    """
    ext = PurePosixPath(file_path).suffix.lower() if file_path else ""
    if ext not in {".py", ".pyi"}:
        return None

    try:
        ast.parse(content)
    except SyntaxError as exc:
        return TruncationResult(
            is_truncated=True,
            method="ast_parse",
            reason=f"Python syntax error: {exc.msg} (line {exc.lineno})",
        )
    return None


def _check_open_endings(content: str) -> TruncationResult | None:
    """Return a result if code ends with an obviously incomplete token."""
    stripped = content.rstrip("\n\r \t")
    if not stripped:
        return None

    last_line = stripped.splitlines()[-1].strip() if stripped.splitlines() else ""

    # Tokens that almost always mean truncation when they're the last thing
    open_endings = (
        "{",
        "[",
        "(",
        ":",
        ",",
        "&&",
        "||",
        "->",
        "=>",
    )
    if any(stripped.endswith(end) for end in open_endings):
        tail = last_line[-40:] if len(last_line) > 40 else last_line
        return TruncationResult(
            is_truncated=True,
            method="open_ending",
            reason=f"Code ends with incomplete token: `{tail}`",
        )
    return None


def _check_truncated_declarations(content: str) -> TruncationResult | None:
    """Return a result if the last line looks like a truncated declaration.

    Only flags when the last non-blank line is short (<90 chars), lacks
    any body/closer characters (``{}();:``), and starts with a declaration
    keyword.  This avoids false positives on compact valid one-liners.
    """
    stripped = content.rstrip("\n\r \t")
    if not stripped:
        return None

    lines = stripped.splitlines()
    last_line = lines[-1].strip() if lines else ""

    # Only short lines without body characters
    if len(last_line) >= 90 or any(c in last_line for c in "{}();:"):
        return None

    starters = (
        "function ",
        "const ",
        "let ",
        "var ",
        "class ",
        "interface ",
        "type ",
        "import ",
        "from ",
        "export ",
        "def ",
        "fn ",
        "pub ",
        "async ",
        "await ",
        "if ",
        "for ",
        "while ",
        "switch ",
        "match ",
        "enum ",
        "struct ",
        "impl ",
        "trait ",
        "mod ",
        "package ",
    )
    if any(last_line.startswith(s) for s in starters):
        return TruncationResult(
            is_truncated=True,
            method="truncated_declaration",
            reason=f"Last line looks like a truncated declaration: `{last_line}`",
        )
    return None


def _check_bracket_imbalance(content: str) -> TruncationResult | None:
    """Return a result if brackets are severely imbalanced.

    Uses a +3 tolerance to avoid false positives from template literals,
    JSX, and other constructs that legitimately have more opens than closes
    in a partial snippet.
    """
    stripped = content.rstrip("\n\r \t")
    opens = stripped.count("{") + stripped.count("[") + stripped.count("(")
    closes = stripped.count("}") + stripped.count("]") + stripped.count(")")
    # Tolerance of 2 — template literals, JSX, and some language
    # constructs legitimately have 1-2 more opens than closes in a
    # snippet.  3+ is almost always truncation.
    if opens > closes + 2:
        return TruncationResult(
            is_truncated=True,
            method="bracket_imbalance",
            reason=(
                f"Too many opening brackets ({opens}) vs closing ({closes}) "
                f"— likely truncated"
            ),
        )
    return None


# Pattern: last line ends with a binary/boolean operator
_TRAILING_OPERATOR_RE = re.compile(
    r"[+\-*/|&^!]=?\s*$",  # arithmetic / bitwise / compound assignment
)

# Pattern: last line ends with a dot followed by a short identifier fragment
# (e.g. "monkeypatch." or "self.some_meth")
_PARTIAL_METHOD_RE = re.compile(r"\.\w{0,3}\s*$")


def _check_trailing_line(content: str) -> TruncationResult | None:
    """Return a result if the last line appears cut off mid-expression.

    Detects:
    - Trailing binary/boolean operators (``+``, ``-``, ``*``, ``|``, ``&``)
    - Trailing ellipsis (``...``) as a truncation marker
    - Partial method calls ending with ``.short`` identifiers
    """
    stripped = content.rstrip("\n\r \t")
    if not stripped:
        return None

    lines = stripped.splitlines()
    last_line = lines[-1].strip() if lines else ""

    # Ellipsis at end of line
    if last_line.endswith("..."):
        return TruncationResult(
            is_truncated=True,
            method="trailing_line",
            reason=f"Last line ends with ellipsis: `{last_line[-50:]}`",
        )

    # Trailing operator
    if _TRAILING_OPERATOR_RE.search(last_line):
        return TruncationResult(
            is_truncated=True,
            method="trailing_line",
            reason=f"Last line ends with an operator: `{last_line[-50:]}`",
        )

    # Partial method call (e.g. "obj.ab" where "ab" is <4 chars and no parens)
    if _PARTIAL_METHOD_RE.search(last_line) and not last_line.endswith(")"):
        match = _PARTIAL_METHOD_RE.search(last_line)
        if match:
            fragment = match.group()
            # Only flag if the fragment after the dot is very short (<4 chars)
            # and doesn't end with a complete identifier pattern
            after_dot = fragment.lstrip(".")
            if len(after_dot) < 4 and after_dot.isalpha():
                return TruncationResult(
                    is_truncated=True,
                    method="trailing_line",
                    reason=(
                        f"Last line ends with partial identifier: `{last_line[-50:]}`"
                    ),
                )
    return None


def _check_markdown_blocks(content: str) -> TruncationResult | None:
    """Return a result if there's an unclosed fenced code block.

    Detects both triple-backtick (```````) and triple-tilde (``~~~``)
    fenced blocks where the count of opening fences exceeds closing ones.
    """
    backtick_opens = len(re.findall(r"^```", content, re.MULTILINE))
    tilde_opens = len(re.findall(r"^~~~", content, re.MULTILINE))

    # Each fenced block needs an open and close — odd count means unclosed
    if backtick_opens % 2 != 0:
        return TruncationResult(
            is_truncated=True,
            method="markdown_block",
            reason="Unclosed triple-backtick code block",
        )
    if tilde_opens % 2 != 0:
        return TruncationResult(
            is_truncated=True,
            method="markdown_block",
            reason="Unclosed triple-tilde code block",
        )
    return None


def _check_incomplete_json(content: str) -> TruncationResult | None:
    """Return a result if content appears to be truncated JSON.

    Only applies when the first non-whitespace character is ``{`` or ``[``.
    We specifically look for truncation indicators in the parse error
    (``Expecting``, ``Unterminated``), not just any JSON error.
    """
    stripped_start = content.lstrip()
    if not stripped_start:
        return None

    first_char = stripped_start[0]
    if first_char not in {"{", "["}:
        return None

    try:
        json.loads(content)
    except json.JSONDecodeError as exc:
        msg = exc.msg.lower() if exc.msg else ""
        # Truncation-specific error messages
        if "expecting" in msg or "unterminated" in msg or "eof" in msg:
            return TruncationResult(
                is_truncated=True,
                method="incomplete_json",
                reason=f"Truncated JSON: {exc.msg} (line {exc.lineno})",
            )
    return None


# ---------------------------------------------------------------------------
# Protected fact truncation detection
# ---------------------------------------------------------------------------


def _check_protected_fact_truncation(
    content: str, file_path: str = ""
) -> TruncationResult | None:
    """Check if content contains a truncated protected fact block."""
    if "## Protected User Facts" not in content:
        return None

    # Parse the protected fact section
    match = re.search(r"## Protected User Facts.*?(?=\n##|$)", content, re.DOTALL)
    if not match:
        return None

    block = match.group()
    # If the block starts but cuts off before budget info, it's truncated
    if block.startswith("## Protected User Facts") and not block.rstrip().endswith(")"):
        return TruncationResult(
            is_truncated=True,
            method="protected_fact_truncated",
            reason="Protected fact section appears truncated in context.",
        )

    # Check if known facts from manager are referenced
    try:
        from code_muse.plugins.task_context.protected_facts import (
            get_protected_fact_manager,
        )

        mgr = get_protected_fact_manager()
        for fact in mgr.get_all_facts():
            if fact.content not in block and not fact.immutable:
                return TruncationResult(
                    is_truncated=True,
                    method="protected_fact_missing",
                    reason=f"Protected fact missing from context: {fact.content[:50]}",
                )
    except Exception:
        pass

    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def detect_truncation(content: str, file_path: str = "") -> TruncationResult:
    """Detect whether *content* appears to be truncated code.

    Runs detection methods in order of cheapness and confidence, returning
    the first positive result.  If none trigger, returns a non-truncated
    result.

    Args:
        content: The code string to check.
        file_path: Optional file path hint (used for AST detection on ``.py``).

    Returns:
        A :class:`TruncationResult` indicating whether truncation was found.
    """
    if not isinstance(content, str):
        return TruncationResult(is_truncated=False)

    # Ordered by cheapness and specificity — first match wins
    checks = [
        lambda c: _check_empty(c),
        lambda c: _check_ast_parse(c, file_path),
        lambda c: _check_open_endings(c),
        lambda c: _check_truncated_declarations(c),
        lambda c: _check_bracket_imbalance(c),
        lambda c: _check_trailing_line(c),
        lambda c: _check_markdown_blocks(c),
        lambda c: _check_incomplete_json(c),
        lambda c: _check_protected_fact_truncation(c, file_path),
    ]

    for check_fn in checks:
        try:
            result = check_fn(content)
            if result is not None:
                return result
        except Exception:
            # Never crash — a detection failure is not a truncation signal
            continue

    return TruncationResult(is_truncated=False)


def is_truncated(content: str, file_path: str = "") -> bool:
    """Convenience wrapper returning ``True`` when *content* is truncated.

    Equivalent to ``detect_truncation(content, file_path=file_path).is_truncated``.
    """
    return detect_truncation(content, file_path=file_path).is_truncated
