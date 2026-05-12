"""Git operations for the GAC plugin.

Lightweight subprocess wrappers for the commands needed to inspect and stage
changes before an AI-generated commit.
"""

import logging
import subprocess

logger = logging.getLogger(__name__)


def _run_git(args: list[str]) -> subprocess.CompletedProcess[str]:
    """Run a git command, returning the CompletedProcess on failure as well."""
    return subprocess.run(
        ["git", *args],
        capture_output=True,
        text=True,
        check=False,
    )


def get_staged_diff(context_lines: int = 5) -> str:
    """Return the staged diff with *context_lines* of context.

    Returns an empty string when there are no staged changes or the command
    fails (e.g. not inside a git repository).
    """
    result = _run_git(["diff", f"-U{context_lines}", "--cached"])
    if result.returncode != 0:
        logger.debug("git diff --cached failed: %s", result.stderr.strip())
        return ""
    return result.stdout


def get_git_status() -> str:
    """Return a formatted status of staged files only.

    Returns an empty string on failure.
    """
    result = _run_git(["diff", "--name-status", "--staged"])
    if result.returncode != 0:
        logger.debug(
            "git diff --name-status --staged failed: %s", result.stderr.strip()
        )
        return ""

    output = result.stdout.strip()
    if not output:
        return "No changes staged for commit."

    status_map = {
        "M": "modified",
        "A": "new file",
        "D": "deleted",
        "R": "renamed",
        "C": "copied",
        "T": "typechange",
    }

    lines = ["Changes to be committed:"]
    for line in output.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        change_type = parts[0][0]
        file_path = parts[-1]
        label = status_map.get(change_type, "modified")
        lines.append(f"\t{label}:   {file_path}")

    return "\n".join(lines)


def get_diff_stat() -> str:
    """Return ``git diff --cached --stat`` output.

    Returns an empty string on failure.
    """
    result = _run_git(["diff", "--cached", "--stat"])
    if result.returncode != 0:
        logger.debug("git diff --cached --stat failed: %s", result.stderr.strip())
        return ""
    return result.stdout


def get_current_branch() -> str:
    """Return the current branch name.

    Returns an empty string on failure.
    """
    result = _run_git(["rev-parse", "--abbrev-ref", "HEAD"])
    if result.returncode != 0:
        logger.debug(
            "git rev-parse --abbrev-ref HEAD failed: %s", result.stderr.strip()
        )
        return ""
    return result.stdout.strip()


def get_repo_root() -> str:
    """Return the repository root absolute path.

    Returns an empty string on failure.
    """
    result = _run_git(["rev-parse", "--show-toplevel"])
    if result.returncode != 0:
        logger.debug("git rev-parse --show-toplevel failed: %s", result.stderr.strip())
        return ""
    return result.stdout.strip()


def has_staged_changes() -> bool:
    """Return ``True`` if there are staged files."""
    result = _run_git(["diff", "--cached", "--quiet"])
    return result.returncode != 0


def has_any_changes() -> bool:
    """Return ``True`` if there are any changes (staged or unstaged)."""
    result = _run_git(["status", "--porcelain"])
    if result.returncode != 0:
        return False
    return bool(result.stdout.strip())


def stage_all() -> None:
    """Stage all changes with ``git add -A``.

    Logs a warning on failure but does not raise.
    """
    result = _run_git(["add", "-A"])
    if result.returncode != 0:
        logger.warning("git add -A failed: %s", result.stderr.strip())
