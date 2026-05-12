"""Planning Agent - Breaks down complex tasks into actionable steps with strategic roadmapping."""

from code_muse.config import get_agent_name

from .base_agent import BaseAgent
from .prompt_v3 import autonomy_base_prompt, planning_overlay


class PlanningAgent(BaseAgent):
    """Planning Agent - Analyzes requirements and creates detailed execution plans."""

    @property
    def name(self) -> str:
        return "planning-agent"

    @property
    def display_name(self) -> str:
        return "Planning Agent 📋"

    @property
    def description(self) -> str:
        return (
            "Breaks down complex coding tasks into clear, actionable steps. "
            "Analyzes project structure, identifies dependencies, and creates execution roadmaps."
        )

    def get_available_tools(self) -> list[str]:
        """Get the list of tools available to the Planning Agent."""
        return [
            "list_files",
            "read_file",
            "grep",
            "ask_user_question",
            "list_agents",
            "invoke_agent",
            "list_or_search_skills",
        ]

    def get_system_prompt(self) -> str:
        """Get the Planning Agent's system prompt — v3 architecture."""
        agent_name = get_agent_name()

        result = autonomy_base_prompt() + "\n\n" + planning_overlay(agent_name)
        return result
