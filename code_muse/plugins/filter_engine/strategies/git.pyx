"""Git compression strategies for the filter engine.

Parses common git command output and produces compact summaries.
"""

import re

from code_muse.plugins.filter_engine.registry import get_registry
from code_muse.plugins.filter_engine.verbosity import VerbosityLevel
from code_muse.tools.command_runner import ShellCommandOutput


def _compress_plain_git_status(
    stdout: str,
    stderr: str,
    verbosity: VerbosityLevel,
) -> ShellCommandOutput:
    """Fallback parser for human-readable ``git status`` output."""
    lines = stdout.strip().splitlines()

    cdef str branch = "unknown"
    cdef int staged = 0
    cdef int unstaged = 0
    cdef int untracked = 0

    cdef bint in_staged = False
    cdef bint in_unstaged = False
    cdef bint in_untracked = False
    cdef str line
    cdef str raw

    for raw in lines:
        line = raw.strip()
        if line.startswith("On branch "):
            branch = line[10:].strip()
        elif line.startswith("HEAD detached "):
            branch = line[14:].strip().split()[0]
        elif line == "Changes to be committed:":
            in_staged = True
            in_unstaged = False
            in_untracked = False
        elif line == "Changes not staged for commit:":
            in_staged = False
            in_unstaged = True
            in_untracked = False
        elif line == "Untracked files:":
            in_staged = False
            in_unstaged = False
            in_untracked = True
        elif line == "":
            in_staged = in_unstaged = in_untracked = False
        elif line.startswith("("):
            continue
        elif in_staged and any(
            line.startswith(p)
            for p in ("modified:", "new file:", "deleted:", "renamed:", "copied:")
        ):
            staged += 1
        elif in_unstaged and any(
            line.startswith(p) for p in ("modified:", "deleted:", "renamed:")
        ):
            unstaged += 1
        elif in_untracked and not line.startswith("("):
            untracked += 1

    summary = (
        f"branch:{branch} | staged:{staged} unstaged:{unstaged} untracked:{untracked}"
    )
    if verbosity >= VerbosityLevel.VERBOSE:
        summary += f"\n{stdout.strip()}"

    success = not stderr.strip() or "error" not in stderr.lower()
    return ShellCommandOutput(
        success=success,
        command="git status",
        stdout=summary,
        stderr=stderr if verbosity >= VerbosityLevel.VERY_VERBOSE else None,
        exit_code=0,
        execution_time=None,
    )


def compress_git_status(
    stdout: str,
    stderr: str,
    verbosity: VerbosityLevel,
) -> ShellCommandOutput:
    """Compress ``git status`` output into a compact summary.

    Parses porcelain-style status lines and counts staged, unstaged, and
    untracked files.  Also extracts branch name and ahead/behind counts.

    Falls back to a plain-text parser when the output does not look like
    porcelain (e.g. the user ran ``git status`` without ``--porcelain``).

    Args:
        stdout: Raw command stdout.
        stderr: Raw command stderr.
        verbosity: Current verbosity level.

    Returns:
        A :class:`ShellCommandOutput` with the compressed summary.
    """
    lines = stdout.strip().splitlines()

    # Detect plain (human-readable) git status output
    if lines and (
        lines[0].startswith("On branch ")
        or lines[0].startswith("HEAD detached ")
        or lines[0].startswith("nothing to commit")
    ):
        return _compress_plain_git_status(stdout, stderr, verbosity)

    cdef str branch = "unknown"
    cdef int ahead = 0
    cdef int behind = 0

    cdef int staged = 0
    cdef int unstaged = 0
    cdef int untracked = 0

    file_lists: dict[str, list[str]] = {
        "M": [],
        "A": [],
        "D": [],
        "??": [],
    }

    cdef str line
    cdef str xy
    cdef str filename
    cdef str index_char
    cdef str worktree_char
    cdef object branch_match
    cdef object ahead_match
    cdef object behind_match

    for line in lines:
        line = line.rstrip("\r")
        if line.startswith("##"):
            # Branch line: ## main...origin/main [ahead 2, behind 1]
            branch_match = re.search(r"##\s+([^.\s]+)", line)
            if branch_match:
                branch = branch_match.group(1)
            ahead_match = re.search(r"ahead\s+(\d+)", line)
            if ahead_match:
                ahead = int(ahead_match.group(1))
            behind_match = re.search(r"behind\s+(\d+)", line)
            if behind_match:
                behind = int(behind_match.group(1))
            continue

        if len(line) >= 2 and (line.startswith("??") or line[0] in " MADRC"):
            # Porcelain status line: XY filename
            xy = line[:2]
            filename = line[3:] if len(line) > 3 else ""

            if xy == "??":
                untracked += 1
                file_lists["??"].append(filename)
            else:
                index_char = xy[0]
                worktree_char = xy[1]
                if index_char in "MADRC":
                    staged += 1
                    if index_char in file_lists:
                        file_lists[index_char].append(filename)
                if worktree_char in "MADRC":
                    unstaged += 1
                    if worktree_char in file_lists:
                        file_lists[worktree_char].append(filename)

    summary = (
        f"branch:{branch} ↑{ahead} ↓{behind} | "
        f"M:{len(file_lists['M'])} A:{len(file_lists['A'])} "
        f"D:{len(file_lists['D'])} ??{len(file_lists['??'])}"
    )

    if verbosity >= VerbosityLevel.VERBOSE:
        parts = [summary]
        for key, files in file_lists.items():
            if files:
                parts.append(f"{key}: {', '.join(files[:20])}")
                if len(files) > 20:
                    parts.append(f"  ... and {len(files) - 20} more")
        summary = "\n".join(parts)

    success = not stderr.strip() or "error" not in stderr.lower()
    return ShellCommandOutput(
        success=success,
        command="git status",
        stdout=summary,
        stderr=stderr if verbosity >= VerbosityLevel.VERY_VERBOSE else None,
        exit_code=0,
        execution_time=None,
    )


def compress_git_log(
    stdout: str,
    stderr: str,
    verbosity: VerbosityLevel,
) -> ShellCommandOutput:
    """Compress ``git log --oneline`` output into a compact summary.

    Args:
        stdout: Raw command stdout.
        stderr: Raw command stderr.
        verbosity: Current verbosity level.

    Returns:
        A :class:`ShellCommandOutput` with the compressed summary.
    """
    lines = [line for line in stdout.strip().splitlines() if line.strip()]
    cdef int count = len(lines)

    if count == 0:
        return ShellCommandOutput(
            success=True,
            command="git log",
            stdout="0 commits",
            stderr=stderr if verbosity >= VerbosityLevel.VERY_VERBOSE else None,
            exit_code=0,
            execution_time=None,
        )

    cdef str first_hash = lines[0][:7] if lines[0] else ""
    cdef str last_hash = lines[-1][:7] if lines[-1] else ""

    # Extract commit messages (after the hash)
    messages: list[str] = []
    cdef list parts
    cdef str line
    cdef str msg

    for line in lines:
        parts = line.split(None, 1)
        if len(parts) > 1:
            messages.append(parts[1])
        else:
            messages.append(line)

    preview = ", ".join(messages[:3])
    if len(messages) > 3:
        preview += f", ... ({len(messages) - 3} more)"

    summary = f"{count} commits ({first_hash}..{last_hash}): {preview}"

    if verbosity >= VerbosityLevel.VERBOSE:
        summary = f"{count} commits ({first_hash}..{last_hash}):\n" + "\n".join(
            f"  {line[:7]} {msg}" for line, msg in zip(lines, messages, strict=False)
        )

    success = not stderr.strip() or "error" not in stderr.lower()
    return ShellCommandOutput(
        success=success,
        command="git log",
        stdout=summary,
        stderr=stderr if verbosity >= VerbosityLevel.VERY_VERBOSE else None,
        exit_code=0,
        execution_time=None,
    )


def compress_git_diff(
    stdout: str,
    stderr: str,
    verbosity: VerbosityLevel,
) -> ShellCommandOutput:
    """Compress ``git diff`` output into a compact summary.

    When *verbosity* is :attr:`~VerbosityLevel.VERBOSE` or higher the raw
    diff is preserved.  Otherwise parses ``--stat`` style output or falls
    back to counting changed hunks.

    Args:
        stdout: Raw command stdout.
        stderr: Raw command stderr.
        verbosity: Current verbosity level.

    Returns:
        A :class:`ShellCommandOutput` with the compressed summary.
    """
    if verbosity >= VerbosityLevel.VERBOSE:
        # Return full diff at -v and above
        success = not stderr.strip() or "error" not in stderr.lower()
        return ShellCommandOutput(
            success=success,
            command="git diff",
            stdout=stdout,
            stderr=stderr,
            exit_code=0,
            execution_time=None,
        )

    cdef int files_changed = 0
    cdef int insertions = 0
    cdef int deletions = 0
    cdef bint stat_found = False

    stat_pattern = re.compile(
        r"^\s*(\d+) files? changed, (\d+) insertions?\(\+\), (\d+) deletions?\(-\)"
    )

    cdef str line
    cdef object match

    for line in stdout.splitlines():
        if not stat_found:
            match = stat_pattern.search(line)
            if match:
                files_changed = int(match.group(1))
                insertions = int(match.group(2))
                deletions = int(match.group(3))
                stat_found = True
                continue
        if line.startswith("diff --git"):
            files_changed += 1
        elif line.startswith("+") and not line.startswith("+++"):
            insertions += 1
        elif line.startswith("-") and not line.startswith("---"):
            deletions += 1

    summary = (
        f"{files_changed} files changed, {insertions} "
        f"insertions(+), {deletions} deletions(-)"
    )

    success = not stderr.strip() or "error" not in stderr.lower()
    return ShellCommandOutput(
        success=success,
        command="git diff",
        stdout=summary,
        stderr=stderr if verbosity >= VerbosityLevel.VERY_VERBOSE else None,
        exit_code=0,
        execution_time=None,
    )


def compress_git_mutation(
    stdout: str,
    stderr: str,
    verbosity: VerbosityLevel,
) -> ShellCommandOutput:
    """Compress output from mutating git commands (add, commit, push, pull, etc.).

    Returns a minimal ``"ok"`` or ``"ok <hash>"`` summary.  On error the
    stderr is surfaced.

    Args:
        stdout: Raw command stdout.
        stderr: Raw command stderr.
        verbosity: Current verbosity level.
    """
    cdef bint has_error = bool(stderr.strip()) and (
        "error" in stderr.lower()
        or "fatal" in stderr.lower()
        or "conflict" in stderr.lower()
    )

    if has_error:
        error_msg = stderr.strip().splitlines()[0] if stderr.strip() else "Git error"
        summary = f"ERROR: {error_msg}"
        return ShellCommandOutput(
            success=False,
            command="git",
            stdout=None,
            stderr=summary,
            exit_code=1,
            execution_time=None,
        )

    # Try to extract a commit hash from stdout
    cdef object hash_match = re.search(r"\b([a-f0-9]{7,40})\b", stdout)
    cdef str commit_hash = hash_match.group(1)[:7] if hash_match else ""

    summary = f"ok {commit_hash}" if commit_hash else "ok"

    if verbosity >= VerbosityLevel.VERBOSE and stdout.strip():
        summary += f"\n{stdout.strip()}"

    return ShellCommandOutput(
        success=True,
        command="git",
        stdout=summary,
        stderr=None,
        exit_code=0,
        execution_time=None,
    )


def compress_git(
    command: str,
    stdout: str,
    stderr: str,
    exit_code: int,
    verbosity: VerbosityLevel,
) -> ShellCommandOutput | None:
    """Main dispatcher for git compression strategies.

    Args:
        command: The original git command.
        stdout: Raw stdout from the command.
        stderr: Raw stderr from the command.
        exit_code: Process exit code.
        verbosity: Current verbosity level.

    Returns:
        A compressed :class:`ShellCommandOutput` or ``None`` on error.
    """
    cdef str stripped = command.strip()
    cdef object mutation_pattern

    # Determine subcommand
    if re.search(r"git\s+status", stripped):
        return compress_git_status(stdout, stderr, verbosity)

    if re.search(r"git\s+log", stripped):
        return compress_git_log(stdout, stderr, verbosity)

    if re.search(r"git\s+diff", stripped):
        return compress_git_diff(stdout, stderr, verbosity)

    # Mutations: add, commit, push, pull, fetch, merge, rebase, stash, reset, etc.
    mutation_pattern = re.compile(
        r"git\s+(add|commit|push|pull|fetch|merge|rebase|stash|reset|checkout|branch|tag|remote|init|clone)"
    )
    if mutation_pattern.search(stripped):
        return compress_git_mutation(stdout, stderr, verbosity)

    # Fallback: treat everything else as a mutation
    return compress_git_mutation(stdout, stderr, verbosity)


# ---------------------------------------------------------------------------
# Register with the strategy registry
# ---------------------------------------------------------------------------
get_registry().register("git", compress_git, priority=0)
