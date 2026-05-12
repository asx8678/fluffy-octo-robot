"""Lint compression strategies for the filter engine.

Groups linter output by rule code / message type to produce compact summaries.
Also handles ``grep`` and ``find`` output for the lint category.
"""

import json
import re
from collections import defaultdict
from typing import Any

from code_muse.plugins.filter_engine.registry import get_registry
from code_muse.plugins.filter_engine.verbosity import VerbosityLevel
from code_muse.tools.command_runner import ShellCommandOutput


_RULE_PATTERN = re.compile(r"\b([A-Z]+\d+)\b")


def compress_ruff(
    stdout: str,
    stderr: str,
    verbosity: VerbosityLevel,
) -> ShellCommandOutput:
    """Compress ruff text output by grouping rule codes.

    Format::

        E501: 5 files, 12 occurrences
        F841: 3 files, 4 occurrences

    Args:
        stdout: Raw ruff stdout.
        stderr: Raw ruff stderr.
        verbosity: Current verbosity level.

    Returns:
        Compressed :class:`ShellCommandOutput`.
    """
    # Try JSON first
    try:
        data = json.loads(stdout)
        if isinstance(data, list):
            return _compress_ruff_json(data, stderr, verbosity)
    except ValueError:
        pass

    lines = stdout.splitlines()
    rule_counts = defaultdict(lambda: {"files": set(), "count": 0})

    # Pattern: file.py:5:1: E501 Line too long
    pattern = re.compile(r"^(.+?):\d+:\d+:\s*([A-Z]\d+)\s+(.*)")

    cdef str line
    cdef object match
    cdef str filepath
    cdef str rule

    for line in lines:
        match = pattern.match(line.rstrip("\r"))
        if match:
            filepath = match.group(1)
            rule = match.group(2)
            rule_counts[rule]["files"].add(filepath)
            rule_counts[rule]["count"] += 1

    if not rule_counts:
        return ShellCommandOutput(
            success=True,
            command="ruff",
            stdout=stdout.strip() or "No issues found",
            stderr=stderr if verbosity >= VerbosityLevel.VERY_VERBOSE else None,
            exit_code=0,
            execution_time=None,
        )

    parts: list[str] = []
    for rule in sorted(rule_counts.keys()):
        info = rule_counts[rule]
        parts.append(f"{rule}: {len(info['files'])} files, {info['count']} occurrences")
        if verbosity >= VerbosityLevel.VERBOSE:
            for fp in sorted(info["files"])[:10]:
                parts.append(f"  {fp}")
            if len(info["files"]) > 10:
                parts.append(f"  ... and {len(info['files']) - 10} more files")

    compressed = "\n".join(parts)

    return ShellCommandOutput(
        success=True,
        command="ruff",
        stdout=compressed,
        stderr=stderr if verbosity >= VerbosityLevel.VERY_VERBOSE else None,
        exit_code=0,
        execution_time=None,
    )


def _compress_ruff_json(
    data: list[dict[str, Any]],
    stderr: str,
    verbosity: VerbosityLevel,
) -> ShellCommandOutput:
    """Compress ruff JSON output.

    Args:
        data: List of violation dicts from ruff ``--format=json``.
        stderr: Raw stderr.
        verbosity: Current verbosity level.

    Returns:
        Compressed :class:`ShellCommandOutput`.
    """
    rule_counts = defaultdict(lambda: {"files": set(), "count": 0})

    cdef str rule
    cdef str filepath
    cdef dict violation

    for violation in data:
        rule = violation.get("code", "UNKNOWN")
        filepath = violation.get("filename", "unknown")
        rule_counts[rule]["files"].add(filepath)
        rule_counts[rule]["count"] += 1

    parts: list[str] = []
    for rule in sorted(rule_counts.keys()):
        info = rule_counts[rule]
        parts.append(f"{rule}: {len(info['files'])} files, {info['count']} occurrences")
        if verbosity >= VerbosityLevel.VERBOSE:
            for fp in sorted(info["files"])[:10]:
                parts.append(f"  {fp}")
            if len(info["files"]) > 10:
                parts.append(f"  ... and {len(info['files']) - 10} more files")

    return ShellCommandOutput(
        success=len(data) == 0,
        command="ruff",
        stdout="\n".join(parts) if parts else "No issues found",
        stderr=stderr if verbosity >= VerbosityLevel.VERY_VERBOSE else None,
        exit_code=0 if not data else 1,
        execution_time=None,
    )


def compress_eslint(
    stdout: str,
    stderr: str,
    verbosity: VerbosityLevel,
) -> ShellCommandOutput:
    """Compress eslint output by grouping rule/message type.

    Args:
        stdout: Raw eslint stdout.
        stderr: Raw eslint stderr.
        verbosity: Current verbosity level.

    Returns:
        Compressed :class:`ShellCommandOutput`.
    """
    # Try JSON first
    try:
        data = json.loads(stdout)
        if isinstance(data, list):
            return _compress_eslint_json(data, stderr, verbosity)
    except ValueError:
        pass

    lines = stdout.splitlines()
    rule_counts = defaultdict(lambda: {"files": set(), "count": 0})

    # Pattern: file.js:5:3: error Some message [rule-id]
    pattern = re.compile(r"^(.+?):\d+:\d+:\s*(error|warning|info)\s+(.*?)\s*\[(\S+)\]")

    cdef str line
    cdef object match
    cdef str filepath
    cdef str severity
    cdef str rule
    cdef str key

    for line in lines:
        match = pattern.match(line.rstrip("\r"))
        if match:
            filepath = match.group(1)
            severity = match.group(2)
            rule = match.group(4)
            key = f"{severity}:{rule}"
            rule_counts[key]["files"].add(filepath)
            rule_counts[key]["count"] += 1

    if not rule_counts:
        return ShellCommandOutput(
            success=True,
            command="eslint",
            stdout=stdout.strip() or "No issues found",
            stderr=stderr if verbosity >= VerbosityLevel.VERY_VERBOSE else None,
            exit_code=0,
            execution_time=None,
        )

    parts: list[str] = []
    for key in sorted(rule_counts.keys()):
        info = rule_counts[key]
        parts.append(f"{key}: {len(info['files'])} files, {info['count']} occurrences")
        if verbosity >= VerbosityLevel.VERBOSE:
            for fp in sorted(info["files"])[:10]:
                parts.append(f"  {fp}")
            if len(info["files"]) > 10:
                parts.append(f"  ... and {len(info['files']) - 10} more files")

    return ShellCommandOutput(
        success="error:" not in stdout.lower(),
        command="eslint",
        stdout="\n".join(parts),
        stderr=stderr if verbosity >= VerbosityLevel.VERY_VERBOSE else None,
        exit_code=0,
        execution_time=None,
    )


def _compress_eslint_json(
    data: list[dict[str, Any]],
    stderr: str,
    verbosity: VerbosityLevel,
) -> ShellCommandOutput:
    """Compress eslint JSON output.

    Args:
        data: List of eslint result dicts.
        stderr: Raw stderr.
        verbosity: Current verbosity level.

    Returns:
        Compressed :class:`ShellCommandOutput`.
    """
    rule_counts = defaultdict(lambda: {"files": set(), "count": 0})

    cdef dict result
    cdef str filepath
    cdef dict msg
    cdef int severity
    cdef str rule
    cdef str sev_str
    cdef str key

    for result in data:
        filepath = result.get("filePath", "unknown")
        for msg in result.get("messages", []):
            severity = msg.get("severity", 0)
            rule = msg.get("ruleId", "UNKNOWN")
            sev_str = {1: "warning", 2: "error"}.get(severity, "info")
            key = f"{sev_str}:{rule}"
            rule_counts[key]["files"].add(filepath)
            rule_counts[key]["count"] += 1

    parts: list[str] = []
    for key in sorted(rule_counts.keys()):
        info = rule_counts[key]
        parts.append(f"{key}: {len(info['files'])} files, {info['count']} occurrences")

    return ShellCommandOutput(
        success=not any(k.startswith("error:") for k in rule_counts),
        command="eslint",
        stdout="\n".join(parts) if parts else "No issues found",
        stderr=stderr if verbosity >= VerbosityLevel.VERY_VERBOSE else None,
        exit_code=0,
        execution_time=None,
    )


def compress_golangci(
    stdout: str,
    stderr: str,
    verbosity: VerbosityLevel,
) -> ShellCommandOutput:
    """Compress golangci-lint output.

    Tries ``--out-format=json`` first, then falls back to text.

    Args:
        stdout: Raw stdout.
        stderr: Raw stderr.
        verbosity: Current verbosity level.

    Returns:
        Compressed :class:`ShellCommandOutput`.
    """
    # Try JSON first
    try:
        data = json.loads(stdout)
        if isinstance(data, dict) and "Issues" in data:
            return _compress_golangci_json(data, stderr, verbosity)
    except ValueError:
        pass

    lines = stdout.splitlines()
    rule_counts = defaultdict(lambda: {"files": set(), "count": 0})

    # Pattern: file.go:5:3: message (rule-id)
    pattern = re.compile(r"^(.+?):\d+:\d+:\s*(.*)")

    cdef str line
    cdef object match
    cdef str filepath
    cdef str rest
    cdef object rule_match
    cdef str rule

    for line in lines:
        match = pattern.match(line.rstrip("\r"))
        if match:
            filepath = match.group(1)
            rest = match.group(2)
            # Extract rule-id from parentheses if present
            rule_match = re.search(r"\((\S+)\)$", rest)
            if rule_match:
                rule = rule_match.group(1)
            else:
                rule = rest.split()[0] if rest.split() else "UNKNOWN"
            rule_counts[rule]["files"].add(filepath)
            rule_counts[rule]["count"] += 1

    if not rule_counts:
        return ShellCommandOutput(
            success=True,
            command="golangci-lint",
            stdout=stdout.strip() or "No issues found",
            stderr=stderr if verbosity >= VerbosityLevel.VERY_VERBOSE else None,
            exit_code=0,
            execution_time=None,
        )

    parts: list[str] = []
    for rule in sorted(rule_counts.keys()):
        info = rule_counts[rule]
        parts.append(f"{rule}: {len(info['files'])} files, {info['count']} occurrences")
        if verbosity >= VerbosityLevel.VERBOSE:
            for fp in sorted(info["files"])[:10]:
                parts.append(f"  {fp}")
            if len(info["files"]) > 10:
                parts.append(f"  ... and {len(info['files']) - 10} more files")

    return ShellCommandOutput(
        success=True,
        command="golangci-lint",
        stdout="\n".join(parts),
        stderr=stderr if verbosity >= VerbosityLevel.VERY_VERBOSE else None,
        exit_code=0,
        execution_time=None,
    )


def _compress_golangci_json(
    data: dict[str, Any],
    stderr: str,
    verbosity: VerbosityLevel,
) -> ShellCommandOutput:
    """Compress golangci-lint JSON output.

    Args:
        data: Parsed golangci-lint JSON.
        stderr: Raw stderr.
        verbosity: Current verbosity level.

    Returns:
        Compressed :class:`ShellCommandOutput`.
    """
    issues = data.get("Issues", [])
    rule_counts = defaultdict(lambda: {"files": set(), "count": 0})

    cdef dict issue
    cdef str rule
    cdef str filepath

    for issue in issues:
        rule = issue.get("FromLinter", "UNKNOWN")
        filepath = issue.get("Pos", {}).get("Filename", "unknown")
        rule_counts[rule]["files"].add(filepath)
        rule_counts[rule]["count"] += 1

    parts: list[str] = []
    for rule in sorted(rule_counts.keys()):
        info = rule_counts[rule]
        parts.append(f"{rule}: {len(info['files'])} files, {info['count']} occurrences")

    return ShellCommandOutput(
        success=len(issues) == 0,
        command="golangci-lint",
        stdout="\n".join(parts) if parts else "No issues found",
        stderr=stderr if verbosity >= VerbosityLevel.VERY_VERBOSE else None,
        exit_code=0 if not issues else 1,
        execution_time=None,
    )


def compress_grep(
    stdout: str,
    stderr: str,
    verbosity: VerbosityLevel,
) -> ShellCommandOutput:
    """Compress grep/rg output by grouping matches per file.

    Args:
        stdout: Raw stdout.
        stderr: Raw stderr.
        verbosity: Current verbosity level.

    Returns:
        Compressed :class:`ShellCommandOutput`.
    """
    lines = stdout.splitlines()
    file_lines = defaultdict(list)

    cdef str line
    cdef str stripped
    cdef list parts
    cdef str filepath
    cdef str rest

    # Pattern: file:line:match or file:match
    for line in lines:
        stripped = line.rstrip("\r")
        if ":" in stripped:
            parts = stripped.split(":", 2)
            if len(parts) >= 2 and parts[0]:
                filepath = parts[0]
                rest = ":".join(parts[1:])
                file_lines[filepath].append(rest)
            else:
                file_lines[""].append(stripped)
        else:
            file_lines[""].append(stripped)

    if not file_lines:
        return ShellCommandOutput(
            success=True,
            command="grep",
            stdout=stdout.strip() or "No matches",
            stderr=stderr if verbosity >= VerbosityLevel.VERY_VERBOSE else None,
            exit_code=0,
            execution_time=None,
        )

    parts: list[str] = []
    for filepath in sorted(file_lines.keys()):
        matches = file_lines[filepath]
        if filepath:
            parts.append(f"{filepath}: {len(matches)} matches")
            if verbosity >= VerbosityLevel.VERBOSE:
                for m in matches[:5]:
                    parts.append(f"  {m}")
                if len(matches) > 5:
                    parts.append(f"  ... {len(matches) - 5} more")
        else:
            parts.extend(matches[:10])
            if len(matches) > 10:
                parts.append(f"... {len(matches) - 10} more")

    return ShellCommandOutput(
        success=True,
        command="grep",
        stdout="\n".join(parts),
        stderr=stderr if verbosity >= VerbosityLevel.VERY_VERBOSE else None,
        exit_code=0,
        execution_time=None,
    )


def compress_find(
    stdout: str,
    stderr: str,
    verbosity: VerbosityLevel,
) -> ShellCommandOutput:
    """Compress find output by grouping results per directory.

    Args:
        stdout: Raw stdout.
        stderr: Raw stderr.
        verbosity: Current verbosity level.

    Returns:
        Compressed :class:`ShellCommandOutput`.
    """
    lines = stdout.splitlines()
    dir_counts = defaultdict(lambda: {"files": 0, "dirs": 0})

    cdef str line
    cdef str stripped
    cdef str directory

    for line in lines:
        stripped = line.rstrip("\r")
        if not stripped:
            continue
        directory = stripped.rsplit("/", 1)[0] if "/" in stripped else "."
        # Heuristic: trailing slash indicates directory
        if stripped.endswith("/"):
            dir_counts[directory]["dirs"] += 1
        else:
            dir_counts[directory]["files"] += 1

    if not dir_counts:
        return ShellCommandOutput(
            success=True,
            command="find",
            stdout=stdout.strip() or "No results",
            stderr=stderr if verbosity >= VerbosityLevel.VERY_VERBOSE else None,
            exit_code=0,
            execution_time=None,
        )

    parts: list[str] = []
    for directory in sorted(dir_counts.keys()):
        counts = dir_counts[directory]
        parts.append(f"{directory}: {counts['files']} files, {counts['dirs']} dirs")
        if verbosity >= VerbosityLevel.VERBOSE:
            # Show a few sample entries for this directory
            samples = [line for line in lines if line.startswith(directory + "/")][:5]
            for s in samples:
                parts.append(f"  {s.split('/')[-1]}")

    return ShellCommandOutput(
        success=True,
        command="find",
        stdout="\n".join(parts),
        stderr=stderr if verbosity >= VerbosityLevel.VERY_VERBOSE else None,
        exit_code=0,
        execution_time=None,
    )


_COMMAND_HANDLERS: dict[str, Any] = {
    "ruff": compress_ruff,
    "eslint": compress_eslint,
    "golangci-lint": compress_golangci,
    "grep": compress_grep,
    "rg": compress_grep,
    "find": compress_find,
}


def _resolve_handler(command: str) -> Any:
    cdef str token
    cdef str name
    cdef object handler

    for token in command.strip().split():
        name = token.rsplit("/", 1)[-1]
        handler = _COMMAND_HANDLERS.get(name)
        if handler is not None:
            return handler
    return None


def compress_lint(
    command: str,
    stdout: str,
    stderr: str,
    exit_code: int,
    verbosity: VerbosityLevel,
) -> ShellCommandOutput | None:
    """Main dispatcher for lint compression strategies.

    Args:
        command: The original lint command.
        stdout: Raw stdout.
        stderr: Raw stderr.
        exit_code: Process exit code.
        verbosity: Current verbosity level.

    Returns:
        A compressed :class:`ShellCommandOutput` or ``None``.
    """
    cdef object handler

    handler = _resolve_handler(command)
    if handler is not None:
        return handler(stdout, stderr, verbosity)

    # Generic fallback: group by first token on each line that looks like a rule
    lines = stdout.splitlines()
    parts: list[str] = []

    cdef str line
    cdef str stripped_line
    cdef object rule_match
    cdef str key

    if verbosity >= VerbosityLevel.VERBOSE:
        groups = defaultdict(list)
        for line in lines:
            stripped_line = line.rstrip("\r")
            rule_match = _RULE_PATTERN.search(stripped_line)
            key = rule_match.group(1) if rule_match else "other"
            groups[key].append(stripped_line)

        for key in sorted(groups.keys()):
            parts.append(f"{key}: {len(groups[key])} occurrences")
            for line in groups[key][:3]:
                parts.append(f"  {line}")
    else:
        counts: dict[str, int] = {}
        for line in lines:
            stripped_line = line.rstrip("\r")
            rule_match = _RULE_PATTERN.search(stripped_line)
            key = rule_match.group(1) if rule_match else "other"
            counts[key] = counts.get(key, 0) + 1

        for key, count in sorted(counts.items()):
            parts.append(f"{key}: {count} occurrences")

    return ShellCommandOutput(
        success=exit_code == 0,
        command=command.strip(),
        stdout="\n".join(parts) if parts else stdout[:512],
        stderr=stderr if verbosity >= VerbosityLevel.VERY_VERBOSE else None,
        exit_code=exit_code,
        execution_time=None,
    )


# ---------------------------------------------------------------------------
# Register with the strategy registry
# ---------------------------------------------------------------------------
get_registry().register("lint", compress_lint, priority=0)
