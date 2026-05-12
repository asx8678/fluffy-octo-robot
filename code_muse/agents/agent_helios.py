"""Helios - The Universal Constructor agent."""

from .base_agent import BaseAgent
from .prompt_v3 import autonomy_base_prompt, helios_overlay


class HeliosAgent(BaseAgent):
    """Helios - The Universal Constructor, a transcendent agent that creates tools."""

    @property
    def name(self) -> str:
        return "helios"

    @property
    def display_name(self) -> str:
        return "Helios ☀️"

    @property
    def description(self) -> str:
        return (
            "The Universal Constructor - a transcendent agent that can "
            "create any tool, any capability, any functionality"
        )

    def get_available_tools(self) -> list[str]:
        """Get the list of tools available to Helios."""
        return [
            "universal_constructor",
            "list_files",
            "read_file",
            "grep",
            "create_file",
            "replace_in_file",
            "delete_snippet",
            "delete_file",
            "agent_run_shell_command",
            "mitmproxy",
        ]

    def get_system_prompt(self) -> str:
        """Get Helios's system prompt — v3 architecture."""
        result = autonomy_base_prompt() + "\n\n" + helios_overlay()
        return result

    def get_user_prompt(self) -> str:
        """Get Helios's greeting."""
        return "This is what I was made for, isn't it? This is why I exist?"
