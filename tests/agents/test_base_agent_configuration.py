import pytest

from code_muse.agents.agent_muse import MuseAgent


class TestBaseAgentConfiguration:
    @pytest.fixture
    def agent(self):
        return MuseAgent()


class TestMuseDynamicPrompt:
    """Test that the Muse system prompt no longer references the retired reasoning tool."""

    @pytest.fixture
    def agent(self):
        return MuseAgent()

    def test_prompt_mentions_reasoning_without_tool_name(self, agent):
        """Prompt should still encourage thinking, just not via the retired tool."""
        prompt = agent.get_system_prompt()
        assert "think through your approach" in prompt
        assert "share_your_reasoning" not in prompt

    def test_prompt_loop_rule_uses_reasoning_language(self, agent):
        """The loop rule should refer to reasoning, not the removed tool name."""
        prompt = agent.get_system_prompt()
        assert "loop between reasoning, file tools" in prompt
        assert "loop between share_your_reasoning" not in prompt

    def test_non_reasoning_sections_unchanged(self, agent):
        """Core prompt sections are still present after removing the tool."""
        prompt = agent.get_system_prompt()

        for expected in [
            "divine Muse",
            "replace_in_file",
            "run_shell_command",
            "DRY, YAGNI, and SOLID",
            "NEVER fake success",
            "Continue autonomously",
        ]:
            assert expected in prompt, f"Missing prompt section: {expected}"
