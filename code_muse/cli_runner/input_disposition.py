"""Input disposition — typed classification of user input for the interactive loop."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class InputDispositionKind(Enum):
    """Enum of possible input classifications.

    Variants:
        SHELL — Shell passthrough command (e.g. ``!ls -la``)
        EXIT — Exit/quit command
        CLEAR — Clear conversation command
        SLASH_HANDLED — Slash command that was fully handled (continue loop)
        SLASH_REWRITE — Slash command that rewrites the input with a new prompt
        TASK — Regular task prompt to send to the agent
    """

    SHELL = "shell"
    EXIT = "exit"
    CLEAR = "clear"
    SLASH_HANDLED = "slash_handled"
    SLASH_REWRITE = "slash_rewrite"
    TASK = "task"


@dataclass(frozen=True)
class InputDisposition:
    """Typed classification of a single user input.

    ``kind`` identifies *what* the input is; ``prompt`` carries an
    optional rewritten payload for ``TASK`` and ``SLASH_REWRITE``
    variants.
    """

    kind: InputDispositionKind
    prompt: str = ""


def classify_input(task: str) -> InputDisposition:
    """Classify a raw user input string into a typed disposition.

    This is intentionally a *pure* function — it inspects the string
    only and returns a value.  No side-effects (no emits, no history
    writes, no command execution).
    """
    from code_muse.command_line.shell_passthrough import is_shell_passthrough

    # ── Shell passthrough ──────────────────────────────────────────────
    if is_shell_passthrough(task):
        return InputDisposition(InputDispositionKind.SHELL)

    stripped_lower = task.strip().lower()

    # ── Exit / quit ────────────────────────────────────────────────────
    if stripped_lower in ("exit", "quit", "/exit", "/quit"):
        return InputDisposition(InputDispositionKind.EXIT)

    # ── Clear ──────────────────────────────────────────────────────────
    if stripped_lower in ("clear", "/clear"):
        return InputDisposition(InputDispositionKind.CLEAR)

    # ── Slash commands ─────────────────────────────────────────────────
    from code_muse.command_line.attachments import parse_prompt_attachments
    from code_muse.command_line.command_handler import handle_command

    processed = parse_prompt_attachments(task)
    cleaned = (processed.prompt or "").strip()

    if cleaned.startswith("/"):
        from code_muse.messaging import emit_error
        try:
            command_result = handle_command(cleaned)
        except Exception as e:
            emit_error(f"Command error: {e}")
            return InputDisposition(InputDispositionKind.SLASH_HANDLED)

        if command_result is True:
            return InputDisposition(InputDispositionKind.SLASH_HANDLED)
        if isinstance(command_result, str):
            return InputDisposition(
                InputDispositionKind.SLASH_REWRITE,
                command_result,
            )
        # False / None → treat as handled (continue loop)
        return InputDisposition(InputDispositionKind.SLASH_HANDLED)

    # ── Regular task ───────────────────────────────────────────────────
    return InputDisposition(InputDispositionKind.TASK, cleaned)
