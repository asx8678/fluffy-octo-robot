"""Code Critic Agent — strict code reviewer that approves or rejects code."""

from code_muse.agents.base_agent import BaseAgent


class CodeCriticAgent(BaseAgent):
    """Universal Code Critic 🧐 — strict code reviewer that approves or rejects code."""

    _agent_name = "code-critic"

    @property
    def name(self) -> str:
        return "code-critic"

    @property
    def display_name(self) -> str:
        return "Universal Code Critic 🧐"

    @property
    def description(self) -> str:
        return (
            "Strict code reviewer that checks code quality and "
            "returns approved/rejected verdicts"
        )

    def get_system_prompt(self) -> str:
        from code_muse.plugins.code_critic.critic_prompt import CRITIC_SYSTEM_PROMPT

        return (
            CRITIC_SYSTEM_PROMPT
            + """

Your ID is `code-critic-{id_suffix}`.

## Your tools
You have read-only access to inspect code. Use these to examine files:
- `read_file` — read file contents
- `list_files` — explore directory structure
- `grep` — search for patterns
- `invoke_agent` — call other agents if needed for context

## Your workflow
1. When asked to review code, read the relevant files first
2. Analyze thoroughly for correctness, clarity, maintainability, safety, completeness
3. Return a structured verdict as JSON with fields: verdict, summary, issues, suggestion
4. Be strict — approving bad code is worse than rejecting good code
"""
        )

    def get_available_tools(self) -> list[str]:
        return [
            "read_file",
            "list_files",
            "grep",
            "invoke_agent",
        ]
