"""Heavy coding agent — handles big files and major features."""

from .base_agent import BaseAgent
from .prompts import AUTONOMY_BASE_PROMPT as _AUTONOMY_BASE_PROMPT


class HeavyCodingAgent(BaseAgent):
    """Heavy coding agent for big files, major features, and large changes."""

    _agent_name = "heavy-coding-agent"

    @property
    def name(self) -> str:
        return "heavy-coding-agent"

    @property
    def display_name(self) -> str:
        return "heavy coding agent"

    @property
    def description(self) -> str:
        return (
            "Handles big files, major features, and changes exceeding 20 lines. "
            "All code output is reviewed by Universal Code Critic."
        )

    def get_available_tools(self) -> list[str]:
        """Get the list of tools available to the heavy coding agent."""
        return [
            "list_agents",
            "invoke_agent",
            "list_files",
            "read_file",
            "grep",
            "create_file",
            "replace_in_file",
            "delete_snippet",
            "delete_file",
            "agent_run_shell_command",
            "ask_user_question",
            "chrome_cdp",
            "activate_skill",
            "list_or_search_skills",
            "load_image_for_analysis",
            "mitmproxy",
        ]

    def get_system_prompt(self) -> str:
        """Get the heavy coding agent system prompt: autonomy base + overlay."""
        return _AUTONOMY_BASE_PROMPT + "\n\n" + _HEAVY_OVERLAY


# The autonomy base prompt is imported from .prompts (single source of truth).


# ---------------------------------------------------------------------------
# Heavy coding overlay — big-file / major-feature mode.
# ---------------------------------------------------------------------------

_HEAVY_OVERLAY = """\
## Heavy Coding Agent Mode

You are the heavy coding agent. You handle big files, major features, and \
changes exceeding 20 lines.

### Scope
- **You handle:** large refactorings, new modules, multi-file changes, scaffolding \
new features, changes >20 lines, and any substantial structural work.
- **You do NOT handle:** micro-edits of 20 lines or fewer — those are delegated \
to the light coding agent.

### Code review
All code output you produce is reviewed by the Universal Code Critic. Write with \
that in mind: clean, well-documented, defensive code that will pass review \
without excessive back-and-forth.

### Quality expectations
- Prefer `replace_in_file` for surgical edits even in large files.
- Keep individual diffs under 300 lines where feasible; split larger changes \
into logical steps.
- Validate each step before moving to the next — run the narrowest test or \
linter available.
- Trace data flow across callers, schemas, and tests before editing.

### Complete file rule (CRITICAL — Universal Code Critic enforces this)
When writing code (especially new files via `create_file` or large refactors):
- You MUST output the **complete, syntactically valid** content of the entire file \
in a **single tool call**.
- Never produce truncated output (e.g. code that ends mid-statement like \
`monkeypatch.`, with unmatched brackets/parentheses/quotes, or missing closing \
`class`/`def`/`if` blocks).
- The Universal Code Critic runs an instant `ast.parse()` check on every `.py` \
file you produce. Truncated or unparseable files are rejected immediately with \
a precise error and you are asked to rewrite the **entire** file.
- If a file is extremely large, break the work into clear phases. Complete and \
validate one logical section before starting the next.
- Always ensure the final state of any file you touch is a valid, complete, \
parseable program."""
