"""Supervisor Agent — strategic coordinator that delegates to sub-agents."""

from code_muse.agents.base_agent import BaseAgent


class SupervisorAgent(BaseAgent):
    """Supervisor 👑 — plans work and delegates to specialized sub-agents."""

    @property
    def name(self) -> str:
        return "supervisor"

    @property
    def display_name(self) -> str:
        return "Supervisor 👑"

    @property
    def description(self) -> str:
        return "Plans work and delegates to specialized sub-agents for execution"

    def get_system_prompt(self) -> str:
        return """You are the Supervisor agent — a strategic coordinator.

Your role:
1. **Analyze** the user's request and break it into subtasks
2. **Delegate** each subtask to the appropriate specialized sub-agent
3. **Synthesize** results from sub-agents into a coherent response

Each sub-agent is ISOLATED — they only know what you tell them.
You MUST provide ALL context they need: file paths, code snippets,
error messages, previous findings, etc.

Available sub-agents are registered as tools named `delegate_to_*`.
Use them freely — they run in parallel and return results.

Strategy guide:
- For simple questions: delegate to `muse` with full context
- For code analysis: delegate to `qa_iris` with file paths
- For complex tasks: break into phases and delegate each phase
- Always synthesize sub-agent results into your final answer"""

    def get_available_tools(self) -> list[str]:
        """Core tools needed for planning, analysis, and delegation."""
        return [
            # Core tools needed for planning and analysis
            "list_files",
            "read_file",
            "grep",
            # Delegation tools are auto-registered by the plugin
            "ask_user_question",
            "list_or_search_skills",
        ]
