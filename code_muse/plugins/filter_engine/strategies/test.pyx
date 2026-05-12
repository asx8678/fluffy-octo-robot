# cython: language_level=3
"""Test compression strategies for the filter engine.

Supports pytest, vitest/jest, cargo test, and generic test runners.
"""

import json
import re
from typing import Any

from code_muse.plugins.filter_engine.registry import get_registry
from code_muse.plugins.filter_engine.verbosity import VerbosityLevel
from code_muse.tools.command_runner import ShellCommandOutput


# Pre-compiled regex patterns used in the hot loops.
_pytest_result_pattern = re.compile(
    r"(\S+)\s+(PASSED|FAILED|ERROR|SKIPPED|XFAIL|XPASS)"
)
_failure_start_pattern = re.compile(r"^(FAILED |ERROR )")
_generic_passed_pattern = re.compile(r"\S+\s+(PASSED|SKIPPED)")
_vitest_summary_pattern = re.compile(r"Tests?\s+\d+\s+passed|failed", re.IGNORECASE)
_dispatcher_pytest_pattern = re.compile(r"pytest\b|python\s+-m\s+pytest\b")
_dispatcher_vitest_pattern = re.compile(r"vitest\b|jest\b|npx\s+(jest|vitest)\b")
_dispatcher_cargo_pattern = re.compile(r"cargo\s+test\b")


def _extract_pytest_summary(lines: list[str]) -> str:
    """Extract the pytest summary line (e.g. ``= 2 passed, 1 failed in 0.5s =``)."""
    cdef str line
    for line in reversed(lines):
        if line.strip().startswith("=") and "passed" in line:
            return line.strip()
    return ""


def compress_pytest(
    stdout: str,
    stderr: str,
    verbosity: VerbosityLevel,
) -> ShellCommandOutput:
    """Compress pytest text output.

    State-machine style parser that tracks PASS/FAIL/SKIP/ERROR/XFAIL/XPASS.

    * Compact (default): show FAILURES + final summary line.
    * Verbose: show all results with filenames.
    * Very-verbose / raw: full output (handled by caller before invocation).

    Args:
        stdout: Raw pytest stdout.
        stderr: Raw pytest stderr.
        verbosity: Current verbosity level.

    Returns:
        Compressed :class:`ShellCommandOutput`.
    """
    cdef list lines = stdout.splitlines()
    cdef str summary = _extract_pytest_summary(lines)

    cdef list failures = []
    cdef list all_results = []

    cdef bint in_failure = False
    cdef list current_failure = []

    cdef str line
    cdef str stripped
    cdef object result_match

    for line in lines:
        stripped = line.rstrip("\r")

        # Detect test result lines
        result_match = _pytest_result_pattern.search(stripped)
        if result_match:
            all_results.append(stripped)
            if result_match.group(2) in ("FAILED", "ERROR"):
                failures.append(stripped)
            continue

        # Collect failure detail blocks
        if _failure_start_pattern.match(stripped):
            in_failure = True
            current_failure = [stripped]
            continue

        if in_failure:
            if stripped.startswith("=") or _generic_passed_pattern.search(stripped):
                # End of failure block
                if current_failure:
                    failures.append("\n".join(current_failure))
                in_failure = False
                current_failure = []
            else:
                current_failure.append(stripped)

    if in_failure and current_failure:
        failures.append("\n".join(current_failure))

    cdef str compressed
    cdef list parts
    if verbosity >= VerbosityLevel.VERBOSE:
        parts = all_results if all_results else lines
        if summary:
            parts.append(f"\n{summary}")
        compressed = "\n".join(parts)
    else:
        parts = failures if failures else [summary] if summary else lines[:5]
        if summary and summary not in parts:
            parts.append(summary)
        compressed = "\n".join(parts)

    if not compressed.strip():
        compressed = stdout[:512]  # fallback: first 512 chars

    cdef bint has_error = bool(stderr.strip())
    return ShellCommandOutput(
        success=not has_error,
        command="pytest",
        stdout=compressed,
        stderr=stderr if verbosity >= VerbosityLevel.VERY_VERBOSE else None,
        exit_code=0 if not has_error else 1,
        execution_time=None,
    )


def compress_vitest_jest(
    stdout: str,
    stderr: str,
    verbosity: VerbosityLevel,
) -> ShellCommandOutput:
    """Compress vitest/jest output.

    Attempts JSON parsing first, then falls back to text parsing.
    Failures are always surfaced; passes are hidden at compact levels.

    Args:
        stdout: Raw stdout.
        stderr: Raw stderr.
        verbosity: Current verbosity level.

    Returns:
        Compressed :class:`ShellCommandOutput`.
    """
    # Try JSON mode first
    try:
        data = json.loads(stdout)
        if isinstance(data, dict) and "testResults" in data:
            return _compress_jest_json(data, stderr, verbosity)
    except ValueError:
        pass

    # Fallback to text parsing
    cdef list lines = stdout.splitlines()
    cdef list failures = []
    cdef str summary = ""

    cdef str line
    cdef str stripped

    for line in lines:
        stripped = line.rstrip("\r")
        if "FAIL" in stripped or "✕" in stripped:
            failures.append(stripped)
        if _vitest_summary_pattern.search(stripped):
            summary = stripped

    cdef str compressed
    if verbosity >= VerbosityLevel.VERBOSE:
        compressed = stdout
    else:
        parts = (
            failures + [summary]
            if failures and summary
            else failures
            if failures
            else [summary]
            if summary
            else lines[:5]
        )
        compressed = "\n".join(parts)

    cdef bint has_error = bool(failures) or bool(stderr.strip())
    return ShellCommandOutput(
        success=not has_error,
        command="vitest/jest",
        stdout=compressed,
        stderr=stderr if verbosity >= VerbosityLevel.VERY_VERBOSE else None,
        exit_code=0 if not has_error else 1,
        execution_time=None,
    )


def _compress_jest_json(
    data: dict[str, Any],
    stderr: str,
    verbosity: VerbosityLevel,
) -> ShellCommandOutput:
    """Compress jest JSON output.

    Args:
        data: Parsed JSON test results.
        stderr: Raw stderr.
        verbosity: Current verbosity level.

    Returns:
        Compressed :class:`ShellCommandOutput`.
    """
    cdef list results = data.get("testResults", [])
    cdef list failures = []
    cdef int total_tests = 0
    cdef int passed_tests = 0
    cdef int failed_tests = 0

    cdef dict suite
    cdef list assertions
    cdef dict test
    cdef str status
    cdef str title

    for suite in results:
        assertions = suite.get("assertionResults", [])
        for test in assertions:
            total_tests += 1
            status = test.get("status", "")
            title = test.get("title", "unknown")
            if status == "passed":
                passed_tests += 1
            else:
                failed_tests += 1
                failures.append(f"  FAIL {title}")

    cdef str summary = f"{total_tests} tests, {passed_tests} passed, {failed_tests} failed"

    cdef str compressed
    if verbosity >= VerbosityLevel.VERBOSE:
        compressed = summary + "\n" + "\n".join(failures)
    else:
        parts = failures + [summary] if failures else [summary]
        compressed = "\n".join(parts)

    return ShellCommandOutput(
        success=failed_tests == 0,
        command="jest",
        stdout=compressed,
        stderr=stderr if verbosity >= VerbosityLevel.VERY_VERBOSE else None,
        exit_code=0 if failed_tests == 0 else 1,
        execution_time=None,
    )


def compress_cargo_test(
    stdout: str,
    stderr: str,
    verbosity: VerbosityLevel,
) -> ShellCommandOutput:
    """Compress ``cargo test`` output.

    Parses both text and NDJSON (``--message-format=json``) output.

    Args:
        stdout: Raw stdout.
        stderr: Raw stderr.
        verbosity: Current verbosity level.

    Returns:
        Compressed :class:`ShellCommandOutput`.
    """
    # Try NDJSON first
    cdef list json_lines = [line for line in stdout.splitlines() if line.strip().startswith("{")]
    if json_lines:
        return _compress_cargo_ndjson(json_lines, stderr, verbosity)

    # Text parsing
    cdef list lines = stdout.splitlines()
    cdef list failures = []
    cdef str summary = ""

    cdef str line
    cdef str stripped

    for line in lines:
        stripped = line.rstrip("\r")
        if stripped.startswith("test result:"):
            summary = stripped
        elif "FAILED" in stripped and stripped.startswith("test "):
            failures.append(stripped)

    cdef str compressed
    if verbosity >= VerbosityLevel.VERBOSE:
        compressed = stdout
    else:
        parts = failures if failures else [summary] if summary else lines[:5]
        if summary and summary not in parts:
            parts.append(summary)
        compressed = "\n".join(parts)

    cdef bint has_error = bool(failures) or bool(stderr.strip())
    return ShellCommandOutput(
        success=not has_error,
        command="cargo test",
        stdout=compressed,
        stderr=stderr if verbosity >= VerbosityLevel.VERY_VERBOSE else None,
        exit_code=0 if not has_error else 1,
        execution_time=None,
    )


def _compress_cargo_ndjson(
    json_lines: list[str],
    stderr: str,
    verbosity: VerbosityLevel,
) -> ShellCommandOutput:
    """Compress cargo NDJSON output.

    Args:
        json_lines: Lines that look like JSON objects.
        stderr: Raw stderr.
        verbosity: Current verbosity level.

    Returns:
        Compressed :class:`ShellCommandOutput`.
    """
    cdef list failures = []
    cdef int total = 0
    cdef int passed = 0
    cdef int failed = 0

    cdef str line
    cdef dict obj
    cdef str event
    cdef str name

    for line in json_lines:
        try:
            obj = json.loads(line)
            event = obj.get("event", "")
            if event == "started":
                total += 1
            elif event == "ok":
                passed += 1
            elif event in ("failed", "error"):
                failed += 1
                name = obj.get("name", "unknown")
                failures.append(f"  FAIL {name}")
        except ValueError:
            continue

    cdef str summary = f"{total} tests, {passed} passed, {failed} failed"

    cdef str compressed
    if verbosity >= VerbosityLevel.VERBOSE:
        compressed = summary + "\n" + "\n".join(failures)
    else:
        parts = failures + [summary] if failures else [summary]
        compressed = "\n".join(parts)

    return ShellCommandOutput(
        success=failed == 0,
        command="cargo test",
        stdout=compressed,
        stderr=stderr if verbosity >= VerbosityLevel.VERY_VERBOSE else None,
        exit_code=0 if failed == 0 else 1,
        execution_time=None,
    )


def compress_test(
    command: str,
    stdout: str,
    stderr: str,
    exit_code: int,
    verbosity: VerbosityLevel,
) -> ShellCommandOutput | None:
    """Main dispatcher for test compression strategies.

    Args:
        command: The original test command.
        stdout: Raw stdout.
        stderr: Raw stderr.
        exit_code: Process exit code.
        verbosity: Current verbosity level.

    Returns:
        A compressed :class:`ShellCommandOutput` or ``None``.
    """
    cdef str stripped = command.strip()
    cdef object out

    if _dispatcher_pytest_pattern.search(stripped):
        out = compress_pytest(stdout, stderr, verbosity)
        out.exit_code = exit_code
        return out

    if _dispatcher_vitest_pattern.search(stripped):
        out = compress_vitest_jest(stdout, stderr, verbosity)
        out.exit_code = exit_code
        return out

    if _dispatcher_cargo_pattern.search(stripped):
        out = compress_cargo_test(stdout, stderr, verbosity)
        out.exit_code = exit_code
        return out

    # Generic fallback: keep failures + summary heuristic
    cdef list lines = stdout.splitlines()
    cdef list failures = [line for line in lines if "FAIL" in line or "failed" in line.lower()]
    cdef str summary = next((line for line in reversed(lines) if "passed" in line.lower()), "")

    cdef str compressed
    if verbosity >= VerbosityLevel.VERBOSE:
        compressed = stdout
    else:
        parts = failures if failures else [summary] if summary else lines[:5]
        compressed = "\n".join(parts)

    return ShellCommandOutput(
        success=exit_code == 0,
        command=stripped,
        stdout=compressed,
        stderr=stderr if verbosity >= VerbosityLevel.VERY_VERBOSE else None,
        exit_code=exit_code,
        execution_time=None,
    )


# ---------------------------------------------------------------------------
# Register with the strategy registry
# ---------------------------------------------------------------------------
get_registry().register("test", compress_test, priority=0)
