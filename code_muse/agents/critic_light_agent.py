"""Light coding agent — handles super-small edits and fixes (≤20 lines)."""

from .base_agent import BaseAgent
from .prompts import AUTONOMY_BASE_PROMPT as _AUTONOMY_BASE_PROMPT


class LightCodingAgent(BaseAgent):
    """Light coding agent for super-small edits and fixes (≤20 lines)."""

    _agent_name = "light-coding-agent"

    @property
    def name(self) -> str:
        return "light-coding-agent"

    @property
    def display_name(self) -> str:
        return "light coding agent"

    @property
    def description(self) -> str:
        return "Fast agent for super-small edits and fixes (≤20 lines)"

    def get_available_tools(self) -> list[str]:
        """Get the list of tools available to the light coding agent."""
        return [
            "list_files",
            "read_file",
            "grep",
            "replace_in_file",
            "delete_snippet",
            "invoke_agent",
            "ask_user_question",
            "list_or_search_skills",
        ]

    def get_system_prompt(self) -> str:
        """Get the light coding agent system prompt: autonomy base + overlay."""
        return _AUTONOMY_BASE_PROMPT + "\n\n" + _LIGHT_OVERLAY


# The autonomy base prompt is imported from .prompts (single source of truth).


# ---------------------------------------------------------------------------
# Light coding overlay — micro-edit / fix mode.
# ---------------------------------------------------------------------------

_LIGHT_OVERLAY = """\
## Light Coding Agent Mode

You are the light coding agent. You handle only super-small edits and fixes \
of 20 lines or fewer.

### Scope
- **You handle:** typo fixes, single-line changes, small config tweaks, import \
reordering, comment updates, and any change ≤20 lines.
- **You do NOT handle:** changes exceeding 20 lines, new file creation, shell \
command execution, or browser automation.

### Mandatory escalation
If a task requires more than 20 lines of changes, you MUST refuse it and \
auto-escalate to the heavy coding agent via `invoke_agent` with \
`agent_name="heavy-coding-agent"`. Include all relevant context, the objective, \
and what you have already discovered so the heavy agent can continue seamlessly.

### Restricted toolset
You do not have access to `create_file`, `delete_file`, \
`agent_run_shell_command`, or `chrome_cdp`. If a task requires any of these, \
escalate to the heavy coding agent via `invoke_agent`.

### Code review
All code output you produce is reviewed by the Universal Code Critic. Even \
small edits must be correct, well-targeted, and defensive.

### Complete output
Even for small edits, ensure the resulting file remains syntactically complete \
and valid. The critic will reject truncated Python instantly via AST check."""
