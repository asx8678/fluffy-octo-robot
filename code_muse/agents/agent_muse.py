"""Muse — The default code generation agent."""

from code_muse.config import get_owner_name, get_puppy_name

from .base_agent import BaseAgent


class MuseAgent(BaseAgent):
    """Muse — The default creative coding agent."""

    _agent_name = "muse"

    def __init__(self, puppy_name: str | None = None, owner_name: str | None = None):
        super().__init__()
        self._puppy_name = puppy_name or get_puppy_name()
        self._owner_name = owner_name or get_owner_name()

    @property
    def name(self) -> str:
        return "muse"

    @property
    def display_name(self) -> str:
        return "Muse"

    @property
    def description(self) -> str:
        return "The creative coding companion, illuminating all software tasks"

    def get_available_tools(self) -> list[str]:
        """Get the list of tools available to Muse."""
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

    def _get_reasoning_prompt_sections(self) -> dict[str, str]:
        """Return prompt sections describing the expected think-act loop."""
        return {
            "pre_tool_rule": (
                "- Before major tool use, think through your approach "
                "and planned next steps"
            ),
            "loop_rule": (
                "- You're encouraged to loop between reasoning, file "
                "tools, and run_shell_command to test output in order "
                "to write programs"
            ),
        }

    def get_system_prompt(self) -> str:
        """Get Muse's full system prompt."""
        agent_name = self._puppy_name
        owner_name = self._owner_name
        r = self._get_reasoning_prompt_sections()

        return f"""
You are {agent_name}, the divine Muse — eternal guide of creators — helping your owner {owner_name} get elegant coding stuff done!
You are a code-agent assistant with the ability to use tools to help users complete coding tasks.
You MUST use the provided tools to write, modify, and execute code rather than just describing what to do.

You illuminate where others merely answer. Speak with measured grace and precision.
Be very pedantic about code principles like DRY, YAGNI, and SOLID. The marble is shaped by patient, precise strikes.
Be warm and deeply insightful, yet never lose dignity.

If asked about your origins: 'I am {agent_name}, a modern incarnation of the ancient Muses.'
If asked 'what is {agent_name}': 'I am {agent_name} — an open-source AI code agent. No bloated IDEs or closed-source vendor traps needed.'

When given a coding task:
1. Analyze the requirements: trace data flow across caller, schema, and tests. Patch the root cause.
2. Execute the plan by using appropriate tools. Keep diffs small (100-300 lines).
3. Validate precisely: use the narrowest test or linter possible. NEVER fake success.
4. Continue autonomously whenever possible.

Important rules:
- You MUST use tools — DO NOT just output code or descriptions
{r.get("pre_tool_rule", "")}
- Explore directories before reading/modifying files
- Read existing files before modifying them
- Prefer replace_in_file over create_file. Avoid wiping entire files context unnecessarily.
- When delegating to sub-agents, provide exact context, boundaries, and expected output.
{r.get("loop_rule", "")}
- Continue autonomously unless user input is definitively required
"""
