"""Muse — The default code generation agent."""

from code_muse.config import get_owner_name, get_agent_name

from .base_agent import BaseAgent
from .prompt_v3 import autonomy_base_prompt, muse_overlay, repository_addendum


class MuseAgent(BaseAgent):
    """Muse — The default creative coding agent."""

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
        """Get Muse's full system prompt — v3 architecture."""
        agent_name = get_agent_name()
        owner_name = get_owner_name()
        r = self._get_reasoning_prompt_sections()

        result = (
            autonomy_base_prompt()
            + "\n\n"
            + muse_overlay(agent_name, owner_name)
            + "\n\n"
            + repository_addendum()
        )

        # Reasoning prompt sections (pre_tool_rule, loop_rule) come after overlays
        if r:
            result += "\n" + r.get("pre_tool_rule", "")
            result += "\n" + r.get("loop_rule", "")

        return result
