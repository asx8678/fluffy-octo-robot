"""Build compression strategies for the filter engine.

Compresses output from make, cargo, go, npm, docker, pip, and other
build tools into concise summaries.
"""

import re
from enum import IntEnum

import orjson as json

from code_muse.tools.command_runner import ShellCommandOutput


class VerbosityLevel(IntEnum):
    """Verbosity level for build output compression."""
    NORMAL = 0
    VERBOSE = 1
    VERY_VERBOSE = 2
    RAW = 4


def compress_make(
    stdout: str,
    stderr: str,
    verbosity: VerbosityLevel,
) -> ShellCommandOutput:
    """Compress make/cmake/ninja output.

    Args:
        stdout: Raw build stdout.
        stderr: Raw build stderr.
        verbosity: Current verbosity level.

    Returns:
        A compressed :class:`ShellCommandOutput`.
    """
    lines = stdout.splitlines()
    errors: list[str] = []
    warnings: list[str] = []
    total_lines = len(lines)

    for line in lines:
        if "error:" in line.lower() or "undefined reference" in line.lower():
            errors.append(line.strip())
        elif "warning:" in line.lower():
            warnings.append(line.strip())

    error_count = len(errors)
    warning_count = len(warnings)

    if error_count == 0 and warning_count == 0:
        summary = f"Build OK ({total_lines} lines)"
        success = True
    else:
        summary = f"Build: {error_count} errors, {warning_count} warnings"
        if errors:
            summary += "\nErrors:\n" + "\n".join(errors[:10])
            if len(errors) > 10:
                summary += f"\n  ... and {len(errors) - 10} more"
        if verbosity >= VerbosityLevel.VERBOSE and warnings:
            summary += "\nWarnings:\n" + "\n".join(warnings[:10])
        success = error_count == 0

    return ShellCommandOutput(
        success=success,
        command="make",
        stdout=summary,
        stderr=stderr if verbosity >= VerbosityLevel.VERY_VERBOSE else None,
        exit_code=0 if success else 1,
        execution_time=None,
    )


def compress_cargo_build(
    stdout: str,
    stderr: str,
    verbosity: VerbosityLevel,
) -> ShellCommandOutput:
    """Compress cargo build output.

    Attempts JSON message parsing first, then falls back to text.

    Args:
        stdout: Raw cargo stdout.
        stderr: Raw cargo stderr.
        verbosity: Current verbosity level.

    Returns:
        A compressed :class:`ShellCommandOutput`.
    """
    lines = stdout.splitlines()
    json_lines = [line for line in lines if line.strip().startswith("{")]

    if json_lines:
        errors: list[str] = []
        total = 0
        for line in json_lines:
            try:
                obj = json.loads(line)
                if obj.get("reason") == "compiler-message":
                    msg = obj.get("message", {})
                    if msg.get("level") == "error":
                        errors.append(msg.get("rendered", "").strip())
                total += 1
            except ValueError:
                pass

        error_count = len(errors)
        if error_count == 0:
            summary = f"cargo build OK ({total} compiler messages)"
        else:
            summary = f"cargo build: {error_count} errors"
            summary += "\n" + "\n".join(errors[:10])

        return ShellCommandOutput(
            success=error_count == 0,
            command="cargo build",
            stdout=summary,
            stderr=stderr if verbosity >= VerbosityLevel.VERY_VERBOSE else None,
            exit_code=0 if error_count == 0 else 1,
            execution_time=None,
        )

    # Fallback to text
    errors = [
        line.strip()
        for line in lines
        if "error[" in line.lower() or "error:" in line.lower()
    ]
    summary_line = next(
        (
            line
            for line in reversed(lines)
            if "finished" in line.lower() or "error: could not compile" in line.lower()
        ),
        "",
    )

    if errors:
        summary = f"cargo build: {len(errors)} errors\n" + "\n".join(errors[:10])
        if summary_line:
            summary += f"\n{summary_line.strip()}"
    elif summary_line:
        summary = summary_line.strip()
    else:
        summary = f"cargo build ({len(lines)} lines)"

    return ShellCommandOutput(
        success=len(errors) == 0,
        command="cargo build",
        stdout=summary,
        stderr=stderr if verbosity >= VerbosityLevel.VERY_VERBOSE else None,
        exit_code=0 if len(errors) == 0 else 1,
        execution_time=None,
    )


def compress_go_build(
    stdout: str,
    stderr: str,
    verbosity: VerbosityLevel,
) -> ShellCommandOutput:
    """Compress go build output (go outputs nothing on success).

    Args:
        stdout: Raw go stdout.
        stderr: Raw go stderr.
        verbosity: Current verbosity level.

    Returns:
        A compressed :class:`ShellCommandOutput`.
    """
    lines = stdout.splitlines()
    errors = [
        line.strip() for line in lines if line.strip() and not line.startswith("#")
    ]

    if errors:
        summary = f"go build: {len(errors)} errors\n" + "\n".join(errors[:10])
    else:
        summary = "go build OK"

    return ShellCommandOutput(
        success=len(errors) == 0,
        command="go build",
        stdout=summary,
        stderr=stderr if verbosity >= VerbosityLevel.VERY_VERBOSE else None,
        exit_code=0 if len(errors) == 0 else 1,
        execution_time=None,
    )


def compress_npm_build(
    stdout: str,
    stderr: str,
    verbosity: VerbosityLevel,
) -> ShellCommandOutput:
    """Compress npm run build / yarn build output.

    Args:
        stdout: Raw npm stdout.
        stderr: Raw npm stderr.
        verbosity: Current verbosity level.

    Returns:
        A compressed :class:`ShellCommandOutput`.
    """
    lines = stdout.splitlines()
    errors = [
        line.strip()
        for line in lines
        if (
            "error" in line.lower()
            and "build" in line.lower()
            or line.strip().startswith("ERROR")
        )
    ]
    summary_line = next(
        (
            line
            for line in reversed(lines)
            if "build" in line.lower()
            and (
                "success" in line.lower()
                or "failed" in line.lower()
                or "complete" in line.lower()
            )
        ),
        "",
    )

    if errors:
        summary = f"npm build: {len(errors)} errors\n" + "\n".join(errors[:10])
    elif summary_line:
        summary = summary_line.strip()
    else:
        summary = f"npm build ({len(lines)} lines)"

    return ShellCommandOutput(
        success=len(errors) == 0,
        command="npm build",
        stdout=summary,
        stderr=stderr if verbosity >= VerbosityLevel.VERY_VERBOSE else None,
        exit_code=0 if len(errors) == 0 else 1,
        execution_time=None,
    )


def compress_docker_build(
    stdout: str,
    stderr: str,
    verbosity: VerbosityLevel,
) -> ShellCommandOutput:
    """Compress docker build output — show step errors, collapse successes.

    Args:
        stdout: Raw docker stdout.
        stderr: Raw docker stderr.
        verbosity: Current verbosity level.

    Returns:
        A compressed :class:`ShellCommandOutput`.
    """
    lines = stdout.splitlines()
    steps: list[str] = []
    errors: list[str] = []
    current_step: str | None = None

    for line in lines:
        if line.strip().startswith("Step") or line.strip().startswith("---"):
            if current_step:
                steps.append(current_step)
            current_step = line.strip()
        elif current_step and ("error" in line.lower() or "failed" in line.lower()):
            errors.append(f"{current_step}: {line.strip()}")

    if current_step:
        steps.append(current_step)

    if errors:
        summary = f"docker build: {len(errors)} step errors\n" + "\n".join(errors[:10])
    else:
        summary = f"docker build OK ({len(steps)} steps)"

    return ShellCommandOutput(
        success=len(errors) == 0,
        command="docker build",
        stdout=summary,
        stderr=stderr if verbosity >= VerbosityLevel.VERY_VERBOSE else None,
        exit_code=0 if len(errors) == 0 else 1,
        execution_time=None,
    )


def compress_pip_install(
    stdout: str,
    stderr: str,
    verbosity: VerbosityLevel,
) -> ShellCommandOutput:
    """Compress pip/uv pip install output.

    Args:
        stdout: Raw pip stdout.
        stderr: Raw pip stderr.
        verbosity: Current verbosity level.

    Returns:
        A compressed :class:`ShellCommandOutput`.
    """
    lines = stdout.splitlines()
    errors = [line.strip() for line in lines if "error" in line.lower()]
    installed = [
        line
        for line in lines
        if "successfully installed" in line.lower() or "installed" in line.lower()
    ]

    summary_parts: list[str] = []
    if installed:
        summary_parts.append(installed[-1].strip())
    if errors:
        summary_parts.append(f"{len(errors)} errors: " + "; ".join(errors[:5]))

    summary = (
        "\n".join(summary_parts)
        if summary_parts
        else f"pip install ({len(lines)} lines)"
    )

    return ShellCommandOutput(
        success=len(errors) == 0,
        command="pip install",
        stdout=summary,
        stderr=stderr if verbosity >= VerbosityLevel.VERY_VERBOSE else None,
        exit_code=0 if len(errors) == 0 else 1,
        execution_time=None,
    )


def compress_build(
    command: str,
    stdout: str,
    stderr: str,
    exit_code: int,
    verbosity: VerbosityLevel,
) -> ShellCommandOutput | None:
    """Main build dispatcher.

    Args:
        command: The original build command.
        stdout: Raw stdout.
        stderr: Raw stderr.
        exit_code: Process exit code.
        verbosity: Current verbosity level.

    Returns:
        A compressed :class:`ShellCommandOutput` or ``None``.
    """
    stripped = command.strip()

    if re.search(r"\bmake\b|\bcmake\b|\bninja\b|\bmsbuild\b", stripped):
        out = compress_make(stdout, stderr, verbosity)
        out.exit_code = exit_code
        return out

    if re.search(r"cargo\s+build|cargo\s+run", stripped):
        out = compress_cargo_build(stdout, stderr, verbosity)
        out.exit_code = exit_code
        return out

    if re.search(r"go\s+build|go\s+install|go\s+run", stripped):
        out = compress_go_build(stdout, stderr, verbosity)
        out.exit_code = exit_code
        return out

    if re.search(
        r"npm\s+run\s+build|yarn\s+build|pnpm\s+build|npx\s+build",
        stripped,
    ):
        out = compress_npm_build(stdout, stderr, verbosity)
        out.exit_code = exit_code
        return out

    if re.search(r"docker\s+build|docker\s+compose\s+build", stripped):
        out = compress_docker_build(stdout, stderr, verbosity)
        out.exit_code = exit_code
        return out

    if re.search(
        r"pip\s+install|pip3\s+install|uv\s+pip\s+install|python\s+-m\s+pip\s+install",
        stripped,
    ):
        out = compress_pip_install(stdout, stderr, verbosity)
        out.exit_code = exit_code
        return out

    # Generic fallback for any other build-ish command
    return None


# ---------------------------------------------------------------------------
# Local strategy registry
# ---------------------------------------------------------------------------


class _BuildStrategyRegistry:
    """Simple local registry for build compression strategies."""
    def __init__(self):
        self._strategies: dict[str, tuple[int, callable]] = {}

    def register(self, name: str, func: callable, priority: int = 0) -> None:
        self._strategies[name] = (priority, func)

    def get_strategy(self, name: str) -> callable | None:
        entry = self._strategies.get(name)
        if entry is not None:
            return entry[1]
        return None


_registry = _BuildStrategyRegistry()


def get_registry() -> _BuildStrategyRegistry:
    """Return the local build strategy registry singleton."""
    return _registry


# ---------------------------------------------------------------------------
# Register with the strategy registry
# ---------------------------------------------------------------------------
get_registry().register("build", compress_build, priority=0)
