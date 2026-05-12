import re

_ARGS_PLACEHOLDER = "{{args}}"

_SHELL_BLOCK_RE = re.compile(r"```(?:bash|shell)", re.IGNORECASE)
_RUN_SHELL_CMD_RE = re.compile(r"agent_run_shell_command", re.IGNORECASE)

# Mapping of command prefix → flag to auto-append
_AUTO_FLAGS: list[tuple[list[str], str]] = [
    (["npm", "install"], "--silent"),
    (["git"], "--no-pager"),
    (["pnpm"], "--silent"),
    (["cargo"], "--quiet"),
    (["pip", "install"], "--quiet"),
    (["yarn"], "--silent"),
]

# Flags that indicate a command already has an efficiency flag set
_EFFICIENCY_FLAGS = {"--silent", "--quiet", "--no-pager"}


def inject_args(prompt: str, args: str) -> str:
    """Replace every occurrence of ``{{args}}`` with *args*.

    If *args* is empty, ``{{args}}`` is replaced with an empty string.
    """
    return prompt.replace(_ARGS_PLACEHOLDER, args)


def detect_shell_blocks(prompt: str) -> bool:
    """Return ``True`` if *prompt* contains shell-related constructs."""
    return bool(_SHELL_BLOCK_RE.search(prompt) or _RUN_SHELL_CMD_RE.search(prompt))


def auto_flag_shell_command(command: str) -> str:
    """Append efficiency flags to known shell commands when missing.

    Only appends a flag if the command is recognized and the flag is
    not already present anywhere in the command string.
    """
    stripped = command.strip()
    if not stripped:
        return command

    # If any efficiency flag is already present, leave the command alone
    if any(flag in stripped for flag in _EFFICIENCY_FLAGS):
        return command

    parts = stripped.split()
    if not parts:
        return command

    for prefixes, flag in _AUTO_FLAGS:
        if len(parts) >= len(prefixes) and parts[: len(prefixes)] == prefixes:
            return stripped + " " + flag

    return command


_FENCED_BLOCK_RE = re.compile(
    r"(```(?:bash|shell)\n)(.*?)(\n```)",
    re.IGNORECASE | re.DOTALL,
)


def _process_block(match: re.Match[str]) -> str:
    """Process a single fenced shell block: apply flags to each line."""
    prefix = match.group(1)
    body = match.group(2)
    suffix = match.group(3)

    lines = body.split("\n")
    processed = [auto_flag_shell_command(line) for line in lines]
    return prefix + "\n".join(processed) + suffix


def apply_shell_flags(prompt: str) -> str:
    """Find fenced shell blocks and apply efficiency flags to each line.

    Returns the prompt with shell commands updated in-place.
    """
    return _FENCED_BLOCK_RE.sub(_process_block, prompt)
