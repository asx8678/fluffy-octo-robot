"""Text transform primitives for shell output minimisation.

Each function is a pure, side-effect-free transform on a string.
They are the building blocks that pipeline definitions compose.

All functions accept ``str`` and return ``str``.  Every primitive is
single-pass, Unicode-safe, and raises on gross misuse but never on
edge-case input (empty string, all-whitespace, etc.).

Includes a comprehensive ``if __name__ == "__main__":`` test block.
"""

import re

from code_muse.terminal_utils import strip_ansi

# ---------------------------------------------------------------------------
# ANSI / control character stripping
# ---------------------------------------------------------------------------

# Re-export the Cython-optimised strip_ansi from terminal_utils for backward
# compatibility and so that downstream pipeline code keeps working.


# ---------------------------------------------------------------------------
# Consecutive-line deduplication
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Consecutive-line deduplication
# ---------------------------------------------------------------------------


def dedup_consecutive_lines(input: str) -> str:
    """Collapse consecutive identical lines into ``line (×N)`` notation.

    Runs of 2+ identical consecutive lines are collapsed.  Blank lines
    participate in deduplication.
    """
    if not input:
        return input

    lines = input.splitlines()
    if len(lines) < 2:
        return input

    result: list[str] = []
    i = 0
    while i < len(lines):
        run_start = i
        line = lines[i]
        # Count how many consecutive identical lines follow
        while i < len(lines) and lines[i] == line:
            i += 1
        run_len = i - run_start
        if run_len >= 2:
            result.append(f"{line} (×{run_len})")
        else:
            result.extend(lines[run_start:i])

    output = "\n".join(result)
    if input.endswith("\n"):
        output += "\n"
    return output


# ---------------------------------------------------------------------------
# Head / tail extraction
# ---------------------------------------------------------------------------


def head_tail_lines(input: str, head: int, tail: int) -> str:
    """Keep *head* first lines and *tail* last lines, with an omission marker.

    Returns::

        <first N lines>
        … <M> lines omitted …
        <last N lines>

    When the input has fewer than ``head + tail`` lines it is returned
    unchanged.
    """
    if not input:
        return input

    lines = input.splitlines()
    total = len(lines)

    if total <= head + tail:
        return input

    head_lines = lines[:head]
    tail_lines = lines[-tail:] if tail > 0 else []
    omitted = total - head - tail

    result = head_lines[:]
    result.append(f"… {omitted} line{'s' if omitted != 1 else ''} omitted …")
    result.extend(tail_lines)

    output = "\n".join(result)
    if input.endswith("\n"):
        output += "\n"
    return output


def head_lines_only(input: str, head: int) -> str:
    """Return first *head* lines with a trailing count line.

    Returns::

        <first N lines>
        (… and <M> more lines)

    When input has ≤ *head* lines it is returned unchanged.
    """
    if not input:
        return input

    lines = input.splitlines()
    total = len(lines)

    if total <= head:
        return input

    kept = lines[:head]
    remainder = total - head
    kept.append(f"(… and {remainder} more line{'s' if remainder != 1 else ''})")

    output = "\n".join(kept)
    if input.endswith("\n"):
        output += "\n"
    return output


def tail_lines_only(input: str, tail: int) -> str:
    """Return last *tail* lines with a leading count line.

    Returns::

        (… <M> lines above …)
        <last N lines>

    When input has ≤ *tail* lines it is returned unchanged.
    """
    if not input:
        return input

    lines = input.splitlines()
    total = len(lines)

    if total <= tail:
        return input

    omitted = total - tail
    result = [f"(… {omitted} line{'s' if omitted != 1 else ''} above …)"]
    result.extend(lines[-tail:])

    output = "\n".join(result)
    if input.endswith("\n"):
        output += "\n"
    return output


# ---------------------------------------------------------------------------
# Regex-based line filtering
# ---------------------------------------------------------------------------


def strip_lines_regex(input: str, patterns: list[str]) -> str:
    """Drop every line that matches any regex in *patterns*.

    Patterns are compiled with ``re.IGNORECASE``.  Lines are split on
    universal newlines.
    """
    if not input or not patterns:
        return input

    compiled = [re.compile(p, re.IGNORECASE) for p in patterns]
    lines = input.splitlines()
    kept = [line for line in lines if not any(c.search(line) for c in compiled)]
    return "\n".join(kept)


def keep_lines_regex(input: str, patterns: list[str]) -> str:
    """Keep only lines that match at least one regex in *patterns*.

    Patterns are compiled with ``re.IGNORECASE``.  Non-matching lines are
    dropped.
    """
    if not input or not patterns:
        return input

    compiled = [re.compile(p, re.IGNORECASE) for p in patterns]
    lines = input.splitlines()
    kept = [line for line in lines if any(c.search(line) for c in compiled)]
    return "\n".join(kept)


# ---------------------------------------------------------------------------
# Per-line truncation
# ---------------------------------------------------------------------------


def truncate_line(line: str, max_chars: int) -> str:
    """Truncate a single line to *max_chars* Unicode codepoints with ``…``.

    When the line is ≤ *max_chars* it is returned unchanged.  The
    ellipsis character counts toward the limit.  Unicode-aware.
    """
    if not line or max_chars <= 0:
        return line

    if len(line) <= max_chars:
        return line

    # Reserve space for the ellipsis
    keep = max_chars - 1
    if keep <= 0:
        return "…"

    return line[:keep] + "…"


# ---------------------------------------------------------------------------
# Listing compactors
# ---------------------------------------------------------------------------


def compact_listing(input: str, max_lines: int) -> str:
    """Compact a plain-text listing to head/tail with an entry count.

    Designed for directory listings, file lists, etc.  Returns::

        <first max_lines entries>
        (… and <N> more entries)
    """
    if not input:
        return input

    lines = input.splitlines()
    total = len(lines)

    if total <= max_lines:
        return input

    kept = lines[:max_lines]
    remainder = total - max_lines
    kept.append(f"(… and {remainder} more entr{'ies' if remainder != 1 else 'y'})")

    return "\n".join(kept)


# ---------------------------------------------------------------------------
# Diagnostics grouper (file:line:message)
# ---------------------------------------------------------------------------


_GLOC_RE = re.compile(r"^(.+?):(\d+):(.*)$")


def group_by_file(input: str, max_per_file: int) -> str:
    """Group ``file:line:message`` diagnostics by file, limiting per file.

    Lines that don't match the ``path:lineno:text`` pattern are passed
    through unchanged.  For each file, only the first *max_per_file*
    diagnostics are kept; the rest are summarised as ``(… N more in <file>)``.
    """
    if not input:
        return input

    lines = input.splitlines()
    unmatched: list[str] = []
    grouped: dict[str, list[str]] = {}
    file_order: list[str] = []

    for line in lines:
        m = _GLOC_RE.match(line)
        if m:
            fname = m.group(1)
            if fname not in grouped:
                grouped[fname] = []
                file_order.append(fname)
            grouped[fname].append(line)
        else:
            unmatched.append(line)

    result: list[str] = []

    for fname in file_order:
        entries = grouped[fname]
        kept = entries[:max_per_file]
        result.extend(kept)
        if len(entries) > max_per_file:
            more = len(entries) - max_per_file
            result.append(f"(… {more} more in {fname})")

    result.extend(unmatched)
    return "\n".join(result)


# ---------------------------------------------------------------------------
# Hard line cap
# ---------------------------------------------------------------------------


def max_lines(input: str, max: int) -> str:
    """Return at most *max* lines, with an omission marker.

    When input has ≤ *max* lines it is returned unchanged.

    Returns::

        <first max lines>
        … N lines omitted …
    """
    if not input:
        return input

    lines = input.splitlines()
    total = len(lines)

    if total <= max:
        return input

    kept = lines[:max]
    omitted = total - max
    kept.append(f"… {omitted} line{'s' if omitted != 1 else ''} omitted …")

    output = "\n".join(kept)
    if input.endswith("\n"):
        output += "\n"
    return output


# ---------------------------------------------------------------------------
# Self-tests
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    failures = 0

    def _check(name: str, got: str, expected: str) -> None:
        global failures
        ok = got == expected
        status = "✅" if ok else "❌ FAIL"
        print(f"{status}  {name}")
        if not ok:
            failures += 1
            print(f"   expected: {expected!r}")
            print(f"   got:      {got!r}")

    # --- strip_ansi ----------------------------------------------------------

    _check("ansi: empty", strip_ansi(""), "")
    _check("ansi: plain text", strip_ansi("hello world"), "hello world")
    _check(
        "ansi: CSI codes stripped",
        strip_ansi("\x1b[32mOK\x1b[0m\n\x1b[1;31mFAIL\x1b[0m"),
        "OK\nFAIL",
    )
    _check(
        "ansi: carriage-return frames to newlines",
        strip_ansi(
            "Downloading... 10%\rDownloading... 50%\rDownloading... 100%\r\nDone!"
        ),
        "Downloading... 10%\nDownloading... 50%\nDownloading... 100%\nDone!",
    )

    # --- dedup_consecutive_lines ---------------------------------------------

    _check("dedup: empty", dedup_consecutive_lines(""), "")
    _check("dedup: single line", dedup_consecutive_lines("hello"), "hello")
    _check(
        "dedup: identical run of 3+",
        dedup_consecutive_lines("a\na\na\nb\nb\nc"),
        "a (×3)\nb (×2)\nc",
    )
    _check(
        "dedup: identical run of 2 collapsed",
        dedup_consecutive_lines("a\na\nb"),
        "a (×2)\nb",
    )
    _check(
        "dedup: blank line run",
        dedup_consecutive_lines("text\n\n\n\ntext"),
        "text\n (×3)\ntext",
    )

    # --- head_tail_lines -----------------------------------------------------

    big = "\n".join(str(i) for i in range(100))
    _check("head_tail: empty", head_tail_lines("", 5, 5), "")
    _check("head_tail: short input", head_tail_lines("1\n2\n3", 5, 5), "1\n2\n3")
    ht = head_tail_lines(big, 3, 2)
    assert ht.startswith("0\n1\n2\n"), f"head wrong: {ht!r}"
    assert "… 95 lines omitted …" in ht
    assert ht.endswith("\n98\n99"), f"tail wrong: {ht!r}"

    # --- head_lines_only -----------------------------------------------------

    _check("head_only: empty", head_lines_only("", 3), "")
    _check("head_only: short", head_lines_only("a\nb", 3), "a\nb")
    hl = head_lines_only(big, 4)
    assert hl.startswith("0\n1\n2\n3\n"), f"head_only wrong start: {hl!r}"
    assert hl.endswith("(… and 96 more lines)"), f"head_only wrong end: {hl!r}"

    # --- tail_lines_only -----------------------------------------------------

    _check("tail_only: empty", tail_lines_only("", 3), "")
    _check("tail_only: short", tail_lines_only("a\nb", 3), "a\nb")
    tl = tail_lines_only(big, 3)
    assert tl.startswith("(… 97 lines above …)\n"), f"tail_only wrong start: {tl!r}"
    assert tl.endswith("\n97\n98\n99"), f"tail_only wrong end: {tl!r}"

    # --- strip_lines_regex ---------------------------------------------------

    _check("strip_re: empty", strip_lines_regex("", [r"err"]), "")
    _check("strip_re: no patterns", strip_lines_regex("a\nb", []), "a\nb")
    _check(
        "strip_re: drop error/warning lines",
        strip_lines_regex(
            "info\nERROR: bad\nWARNING: meh\nok", [r"^error:", r"^warning:"]
        ),
        "info\nok",
    )

    # --- keep_lines_regex ----------------------------------------------------

    _check("keep_re: empty", keep_lines_regex("", [r"err"]), "")
    _check("keep_re: no patterns", keep_lines_regex("a\nb", []), "a\nb")
    _check(
        "keep_re: keep only error lines",
        keep_lines_regex("info\nERROR: bad\nok\nWARN: x", [r"error|warn"]),
        "ERROR: bad\nWARN: x",
    )

    # --- truncate_line -------------------------------------------------------

    _check("trunc: empty", truncate_line("", 10), "")
    _check("trunc: short", truncate_line("abc", 10), "abc")
    _check("trunc: exact", truncate_line("abcdefghij", 10), "abcdefghij")
    _check("trunc: over", truncate_line("abcdefghijk", 10), "abcdefghi…")
    _check("trunc: very narrow", truncate_line("abcdefghijk", 3), "ab…")
    _check("trunc: zero max", truncate_line("abc", 0), "abc")

    # --- compact_listing -----------------------------------------------------

    _check("compact: empty", compact_listing("", 5), "")
    _check("compact: short", compact_listing("a\nb", 5), "a\nb")
    cl = compact_listing(big, 7)
    assert cl.startswith("0\n1\n2\n3\n4\n5\n6\n"), f"compact wrong start: {cl!r}"
    assert cl.endswith("(… and 93 more entries)"), f"compact wrong end: {cl!r}"

    # --- group_by_file -------------------------------------------------------

    diag = "src/a.py:10: error\nsrc/a.py:20: warning\nsrc/b.py:5: error\nextra info"
    _check("group: empty", group_by_file("", 3), "")
    _check("group: non-diag passthrough", group_by_file("plain text", 3), "plain text")
    gb = group_by_file(diag, 1)
    assert "src/a.py:10: error\n(… 1 more in src/a.py)" in gb
    assert "src/b.py:5: error" in gb
    assert "extra info" in gb

    # --- max_lines -----------------------------------------------------------

    _check("max: empty", max_lines("", 5), "")
    _check("max: short", max_lines("a\nb", 5), "a\nb")
    ml = max_lines(big, 6)
    assert ml.startswith("0\n1\n2\n3\n4\n5\n"), f"max wrong start: {ml!r}"
    assert ml.endswith("… 94 lines omitted …"), f"max wrong end: {ml!r}"

    # --- summary -------------------------------------------------------------

    if failures:
        print(f"\n{failures} test(s) FAILED", file=sys.stderr)
        sys.exit(1)
    else:
        print("\n🎉 All primitives tests passed!")
