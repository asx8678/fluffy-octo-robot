"""Coverage tests for agents & small gaps (code_muse-ont).

Targeted tests to reach 100% on specific missed lines.
"""

from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock, patch

import pytest

# =============================================================================
# Agent instantiation tests (get_available_tools + get_system_prompt)
# =============================================================================


_REVIEWER_AGENTS = [
    ("code_muse.agents.agent_qa_kitten", "QualityAssuranceMelpomeneAgent"),
]


@pytest.mark.parametrize("module_path,class_name", _REVIEWER_AGENTS)
def test_reviewer_agent_tools_and_prompt(module_path, class_name):
    """Exercise get_available_tools() and get_system_prompt() for each surviving agent."""
    import importlib

    mod = importlib.import_module(module_path)
    cls = getattr(mod, class_name)
    agent = cls()

    tools = agent.get_available_tools()
    assert isinstance(tools, list)
    assert len(tools) > 0

    prompt = agent.get_system_prompt()
    assert isinstance(prompt, str)
    assert len(prompt) > 100


class TestPlanningAgent:
    def test_tools_and_prompt(self):
        from code_muse.agents.agent_planning import PlanningAgent

        agent = PlanningAgent()
        tools = agent.get_available_tools()
        assert "list_files" in tools
        assert "invoke_agent" in tools

        prompt = agent.get_system_prompt()
        assert "Planning Mode" in prompt
        assert "Execution plan" in prompt


class TestMuseAgentTools:
    def test_get_available_tools(self):
        from code_muse.agents.agent_muse import MuseAgent

        agent = MuseAgent()
        tools = agent.get_available_tools()
        assert "create_file" in tools
        assert "replace_in_file" in tools
        assert "delete_snippet" in tools
        assert "invoke_agent" in tools


# =============================================================================
# summarization_agent.py gaps
# =============================================================================


class TestSummarizationGaps:
    def test_ensure_thread_pool_recreates_after_shutdown(self):
        """Cover lines 38-40: pool._shutdown check."""
        import code_muse.summarization_agent as mod

        pool = ThreadPoolExecutor(max_workers=1)
        pool.shutdown(wait=False)
        mod._thread_pool = pool

        new_pool = mod._ensure_thread_pool()
        assert new_pool is not pool
        assert not new_pool._shutdown

    def test_summarization_error_with_original(self):
        """Cover lines 66-67: SummarizationError.__init__."""
        from code_muse.summarization_agent import SummarizationError

        orig = ValueError("boom")
        err = SummarizationError("wrapper", original_error=orig)
        assert err.original_error is orig
        assert "wrapper" in str(err)

    def test_run_summarization_sync_agent_init_failure(self):
        """Cover the except branch when get_summarization_agent raises."""
        from code_muse.summarization_agent import (
            SummarizationError,
            run_summarization_sync,
        )

        with (
            patch(
                "code_muse.summarization_agent.get_summarization_agent",
                side_effect=RuntimeError("no model"),
            ),
            pytest.raises(SummarizationError, match="Failed to initialize"),
        ):
            run_summarization_sync("prompt", [])

    def test_run_summarization_sync_llm_failure(self):
        """Cover lines 88-105: the _run_in_thread path and LLM error wrapping."""
        from code_muse.summarization_agent import (
            SummarizationError,
            run_summarization_sync,
        )

        mock_agent = MagicMock()
        mock_agent.run = MagicMock(side_effect=RuntimeError("LLM down"))

        with (
            patch(
                "code_muse.summarization_agent.get_summarization_agent",
                return_value=mock_agent,
            ),
            patch(
                "code_muse.summarization_agent.get_summarization_model_name",
                return_value="test",
            ),
            patch("code_muse.model_utils.prepare_prompt_for_model") as mock_prep,
        ):
            mock_prep.return_value = MagicMock(user_prompt="p", instructions="i")
            with pytest.raises(SummarizationError, match="LLM call failed"):
                run_summarization_sync("summarize", [])


# =============================================================================
# display.py line 39 – subagent early return
# =============================================================================


class TestDisplaySubagentSkip:
    def test_skips_when_subagent_not_verbose(self):
        """Cover line 39: early return for subagent without verbose."""
        from code_muse.tools.display import display_non_streamed_result

        with (
            patch("code_muse.tools.display.is_subagent", return_value=True),
            patch("code_muse.tools.display.get_subagent_verbose", return_value=False),
            patch("code_muse.messaging.spinner.pause_all_spinners") as mock_pause,
        ):
            display_non_streamed_result("hello")
            mock_pause.assert_not_called()  # Should have returned early


# =============================================================================
# __init__.py lines 8-10 – exception fallback
# =============================================================================


class TestInitVersionFallback:
    def test_version_fallback_on_exception(self):
        """Cover lines 8-10: exception branch."""
        with patch("importlib.metadata.version", side_effect=Exception("nope")):
            # Re-exec the module code
            import importlib

            import code_muse

            importlib.reload(code_muse)
            assert code_muse.__version__ == "0.0.0-dev"

    def test_version_fallback_on_empty(self):
        """Cover the empty-string branch."""
        with patch("importlib.metadata.version", return_value=""):
            import importlib

            import code_muse

            importlib.reload(code_muse)
            assert code_muse.__version__ == "0.0.0-dev"


# =============================================================================
# __main__.py lines 7-10
# =============================================================================


class TestMainModule:
    def test_main_module_importable(self):
        """Cover the import of __main__ (lines 7-10 minus __name__ guard)."""
        import code_muse.__main__  # noqa: F401
        # The if __name__ == '__main__' guard won't fire, but the import covers lines 7-8


# =============================================================================
# spinner_base.py gaps
# =============================================================================


class TestSpinnerBaseGaps:
    def _make_spinner(self):
        """Create a concrete spinner subclass for testing."""
        from code_muse.messaging.spinner.spinner_base import SpinnerBase

        class DummySpinner(SpinnerBase):
            def start(self):
                super().start()

            def stop(self):
                super().stop()

            def update_frame(self):
                super().update_frame()

        return DummySpinner()

    def test_update_frame_when_not_spinning(self):
        """Cover line 54: update_frame does nothing when not spinning."""
        s = self._make_spinner()
        assert not s.is_spinning
        s.update_frame()
        assert s._frame_index == 0  # unchanged

    def test_update_frame_when_spinning(self):
        s = self._make_spinner()
        s.start()
        s.update_frame()
        assert s._frame_index == 1

    def test_clear_context_info(self):
        """Cover line 70: clear_context_info."""
        from code_muse.messaging.spinner.spinner_base import SpinnerBase

        SpinnerBase.set_context_info("something")
        assert SpinnerBase.get_context_info() == "something"
        SpinnerBase.clear_context_info()
        assert SpinnerBase.get_context_info() == ""

    def test_format_context_info_zero_capacity(self):
        """Cover line 93: capacity <= 0 returns empty."""
        from code_muse.messaging.spinner.spinner_base import SpinnerBase

        assert SpinnerBase.format_context_info(100, 0, 0.0) == ""
        assert SpinnerBase.format_context_info(100, -1, 0.0) == ""

    def test_format_context_info_normal(self):
        from code_muse.messaging.spinner.spinner_base import SpinnerBase

        result = SpinnerBase.format_context_info(5000, 10000, 0.5)
        assert "5,000" in result
        assert "50.0%" in result


# =============================================================================
# ask_user_question/models.py lines 57-59 – timeout_response
# =============================================================================


class TestAskUserQuestionModelsGaps:
    def test_timeout_response(self):
        """Cover lines 57-59: timeout_response classmethod."""
        from code_muse.tools.ask_user_question.models import AskUserQuestionOutput

        resp = AskUserQuestionOutput.timeout_response(30)
        assert resp.timed_out is True
        assert resp.cancelled is False
        assert "30 seconds" in resp.error
        assert not resp.success


# =============================================================================
# ask_user_question/registration.py line 87
# =============================================================================


class TestAskUserRegistrationGap:
    def test_handler_called(self):
        """Cover line 87: the actual handler invocation."""
        from code_muse.tools.ask_user_question.models import AskUserQuestionOutput

        mock_output = AskUserQuestionOutput(cancelled=True)

        with patch(
            "code_muse.tools.ask_user_question.registration._ask_user_question_impl",
            return_value=mock_output,
        ) as mock_impl:
            # We need to register the tool on a real agent, or just call the inner function
            # Simplest: import and call the impl wrapper directly
            from code_muse.tools.ask_user_question.registration import (
                register_ask_user_question,
            )

            mock_agent = MagicMock()
            # Capture the decorated function
            registered_fn = None

            def capture_tool(fn):
                nonlocal registered_fn
                registered_fn = fn
                return fn

            mock_agent.tool = capture_tool
            register_ask_user_question(mock_agent)

            assert registered_fn is not None
            # Call it with a mock context
            result = registered_fn(
                MagicMock(),
                [
                    {
                        "question": "q",
                        "header": "h",
                        "options": [{"label": "a"}, {"label": "b"}],
                    }
                ],
            )
            mock_impl.assert_called_once()
            assert result is mock_output
