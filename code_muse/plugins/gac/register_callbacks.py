"""Register GAC slash commands: /gac, /gac push, /gac bump."""

import logging

from code_muse.callbacks import register_callback
from code_muse.plugins.gac.git_ops import (
    has_any_changes,
    has_staged_changes,
    stage_all,
)
from code_muse.plugins.gac.prompt import build_gac_prompt

logger = logging.getLogger(__name__)

# Import CustomCommandResult from the custom_commands plugin
try:
    from code_muse.plugins.custom_commands.register_callbacks import (
        CustomCommandResult,
    )
except ImportError:
    CustomCommandResult = None


def _on_custom_command(command: str, name: str):
    """Handle /gac, /gac push, /gac bump commands.

    Args:
        command: Full command string (e.g. ``"/gac push"``).
        name: Command name extracted by the handler (``"gac"``).

    Returns:
        - ``CustomCommandResult(prompt)`` when the command is resolved and
          should be sent to the agent as input.
        - ``True`` when there is nothing to commit (already handled).
        - ``None`` if the command is not recognised (passthrough).
    """
    if name != "gac":
        return None

    parts = command.split()
    rest = " ".join(parts[1:]).lower() if len(parts) > 1 else ""

    push = "push" in rest
    bump = "bump" in rest

    # Check for changes (skip for bump — the agent creates the change)
    if not bump and not has_any_changes():
        from code_muse.messaging import emit_warning

        emit_warning("No changes to commit.")
        return True

    # Stage all changes if nothing is staged
    if not has_staged_changes():
        stage_all()

    # Build the prompt
    prompt = build_gac_prompt(push=push, bump=bump)
    if prompt is None:
        from code_muse.messaging import emit_warning

        emit_warning("No changes to commit.")
        return True

    if CustomCommandResult is not None:
        return CustomCommandResult(prompt)

    # Fallback: return prompt as string (will be displayed, not sent to agent)
    return prompt


def _on_custom_command_help():
    """Return help entries for GAC commands."""
    return [
        ("gac", "Generate commit message and commit staged changes"),
        ("gac push", "Generate commit message, commit, and push to remote"),
        ("gac bump", "Bump patch version, commit, and push to remote"),
    ]


register_callback("custom_command", _on_custom_command)
register_callback("custom_command_help", _on_custom_command_help)
