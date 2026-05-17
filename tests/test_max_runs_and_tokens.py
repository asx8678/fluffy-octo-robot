"""Tests for agent max-run limits, usage limits, and token budget configuration.

Covers three gaps found during code review:
1. total_tokens_limit / max_tool_calls config keys are declared but have no getters
2. UsageLimits construction in _runtime.py only passes request_limit
3. Sub-agents pass usage_limits=None, bypassing all limits
"""

from unittest.mock import patch

from pydantic_ai import UsageLimits

from code_muse import config as cp_config
from code_muse.agents import _runtime
from code_muse.config import parser
from code_muse.tools import agent_tools

# ---------------------------------------------------------------------------
# Gap 1: Config getters that don't exist
# ---------------------------------------------------------------------------


class TestMissingConfigGetters:
    """total_tokens_limit and max_tool_calls are in
    get_config_keys() but have no getter."""

    def test_total_tokens_limit_in_get_config_keys(self):
        """The key is listed so it appears in /set tab-completion."""
        keys = cp_config.get_config_keys()
        assert "total_tokens_limit" in keys

    def test_max_tool_calls_in_get_config_keys(self):
        """The key is listed so it appears in /set tab-completion."""
        keys = cp_config.get_config_keys()
        assert "max_tool_calls" in keys

    def test_no_get_total_tokens_limit_function_in_parser(self):
        """No getter exists — users can set it but it does nothing."""
        assert not hasattr(parser, "get_total_tokens_limit")

    def test_no_get_max_tool_calls_function_in_parser(self):
        """No getter exists — users can set it but it does nothing."""
        assert not hasattr(parser, "get_max_tool_calls")

    def test_not_exported_from_config_init(self):
        """These functions are not exported from code_muse.config."""
        assert not hasattr(cp_config, "get_total_tokens_limit")
        assert not hasattr(cp_config, "get_max_tool_calls")


# ---------------------------------------------------------------------------
# Gap 2: UsageLimits construction in _runtime.py only passes request_limit
# ---------------------------------------------------------------------------


class TestUsageLimitsConstruction:
    """_runtime.py constructs UsageLimits with only request_limit."""

    @patch("code_muse.agents._runtime.get_message_limit", return_value=100)
    def test_usage_limits_uses_request_limit_only(self, mock_get_msg_limit):
        """Verify that a default UsageLimits has None for token/tool limits."""
        usage_limits = UsageLimits(request_limit=mock_get_msg_limit())

        assert usage_limits.request_limit == 100
        # These are the default values since we don't pass them
        assert usage_limits.total_tokens_limit is None
        assert usage_limits.tool_calls_limit is None

    def test_runtime_does_not_pass_total_tokens_limit(self):
        """The runtime's UsageLimits construction does NOT
        include total_tokens_limit."""
        source = _runtime.__file__
        with open(source) as f:
            content = f.read()
        # The UsageLimits construction line should exist
        assert "UsageLimits(request_limit=get_message_limit())" in content
        # And should NOT mention total_tokens_limit
        assert "total_tokens_limit" not in content

    def test_runtime_does_not_pass_tool_calls_limit(self):
        """The runtime's UsageLimits construction does NOT include tool_calls_limit."""
        source = _runtime.__file__
        with open(source) as f:
            content = f.read()
        assert "tool_calls_limit" not in content


# ---------------------------------------------------------------------------
# Gap 3: Sub-agents bypass all UsageLimits
# ---------------------------------------------------------------------------


class TestSubAgentUsageLimits:
    """Sub-agent invocations now use get_message_limit()
    instead of silently defaulting to 50."""

    def test_sub_agent_passes_usage_limits_none(self):
        """agent_tools.py no longer passes usage_limits=None to temp_agent.run()."""
        source = agent_tools.__file__
        with open(source) as f:
            content = f.read()
        # The sub-agent run should NOT pass usage_limits=None
        assert "usage_limits=None" not in content
        assert "UsageLimits(request_limit=get_message_limit())" in content

    def test_sub_agent_does_not_read_message_limit(self):
        """Sub-agents now use get_message_limit() to honour
        the user-configured request limit."""
        source = agent_tools.__file__
        with open(source) as f:
            content = f.read()
        assert "get_message_limit" in content


# ---------------------------------------------------------------------------
# Gap 4: get_message_limit() has zero tests
# ---------------------------------------------------------------------------


class TestMessageLimitConfig:
    """get_message_limit() has no tests anywhere — covering it now."""

    def test_default_message_limit(self):
        """Default is 1000 when no config is set."""
        from code_muse.config.parser import get_message_limit

        with patch("code_muse.config.parser.get_value", return_value=None):
            assert get_message_limit() == 1000

    def test_message_limit_from_config(self):
        """Reads the configured value."""
        from code_muse.config.parser import get_message_limit

        with patch("code_muse.config.parser.get_value", return_value="500"):
            assert get_message_limit() == 500

    def test_message_limit_invalid_falls_back_to_default(self):
        """Invalid config values fall back to default."""
        from code_muse.config.parser import get_message_limit

        with patch("code_muse.config.parser.get_value", return_value="not-a-number"):
            assert get_message_limit() == 1000

    def test_message_limit_empty_falls_back_to_default(self):
        """Empty string falls back to default."""
        from code_muse.config.parser import get_message_limit

        with patch("code_muse.config.parser.get_value", return_value=""):
            assert get_message_limit() == 1000

    def test_message_limit_zero(self):
        """Zero is accepted (agent gets zero steps)."""
        from code_muse.config.parser import get_message_limit

        with patch("code_muse.config.parser.get_value", return_value="0"):
            assert get_message_limit() == 0


# ---------------------------------------------------------------------------
# Gap 5: compute_effective_history_budget() has zero tests
# ---------------------------------------------------------------------------


class TestEffectiveHistoryBudget:
    """compute_effective_history_budget() has no tests —
    covering the four model-class tiers.

    ModelFactory.load_config is mocked to return {} so the function
    falls back to out_max = max(4096, min(65536, ctx*0.08)).
    """

    @patch("code_muse.model_factory.ModelFactory.load_config", return_value={})
    def test_large_context_1m_plus(self, _mock_mf):
        """≥1M context: 88% budget (minus out_max 65536 and safety 20000)."""
        from code_muse.config.models import compute_effective_history_budget

        budget = compute_effective_history_budget(1_000_000, overhead=0)
        # 88% of 1M = 880000, out_max=65536, safety=20000
        # budget = 880000 - 65536 - 20000 = 794464
        assert budget == 794_464

    @patch("code_muse.model_factory.ModelFactory.load_config", return_value={})
    def test_medium_context_200k(self, _mock_mf):
        """100k–1M: 74% budget (minus out_max 16000 and safety 4000)."""
        from code_muse.config.models import compute_effective_history_budget

        budget = compute_effective_history_budget(200_000, overhead=0)
        # 74% of 200k = 148000, out_max=16000, safety=4000
        # budget = 148000 - 16000 - 4000 = 128000
        assert budget == 128_000

    @patch("code_muse.model_factory.ModelFactory.load_config", return_value={})
    def test_small_context_64k(self, _mock_mf):
        """32k–100k: 68% budget (minus out_max 5120 and safety 2048)."""
        from code_muse.config.models import compute_effective_history_budget

        budget = compute_effective_history_budget(64_000, overhead=0)
        # 68% of 64k = 43520, out_max=5120, safety=2048
        # budget = 43520 - 5120 - 2048 = 36352
        assert budget == 36_352

    @patch("code_muse.model_factory.ModelFactory.load_config", return_value={})
    def test_tiny_context_16k(self, _mock_mf):
        """<32k: 55% budget clamped to floor of 4096."""
        from code_muse.config.models import compute_effective_history_budget

        budget = compute_effective_history_budget(16_000, overhead=0)
        # 55% of 16k = 8800, out_max=4096, safety=2048
        # budget = 8800 - 4096 - 2048 = 2656, clamped to 4096
        assert budget == 4096

    @patch("code_muse.model_factory.ModelFactory.load_config", return_value={})
    def test_with_overhead(self, _mock_mf):
        """Overhead is subtracted from the budget."""
        from code_muse.config.models import compute_effective_history_budget

        budget = compute_effective_history_budget(200_000, overhead=10_000)
        # 74% of 200k = 148000, minus 10000 overhead, out_max=16000, safety=4000
        # budget = 148000 - 10000 - 16000 - 4000 = 118000
        assert budget == 118_000

    @patch("code_muse.model_factory.ModelFactory.load_config", return_value={})
    def test_overhead_exceeds_budget(self, _mock_mf):
        """When overhead exceeds budget, result is clamped to floor."""
        from code_muse.config.models import compute_effective_history_budget

        budget = compute_effective_history_budget(16_000, overhead=50_000)
        # overhead > max possible budget, result clamped to 4096
        assert budget == 4096


# ---------------------------------------------------------------------------
# Gap 6: filter_huge_message_threshold — getter exists but hidden from /set
# ---------------------------------------------------------------------------


class TestFilterHugeMessageThreshold:
    """filter_huge_message_threshold has a getter but is hidden
    from /set tab-completion."""

    def test_getter_exists(self):
        """The getter function exists."""
        from code_muse.config.parser import get_filter_huge_message_threshold

        assert callable(get_filter_huge_message_threshold)

    def test_not_in_get_config_keys(self):
        """Hidden from /set tab-completion (not in get_config_keys())."""
        keys = cp_config.get_config_keys()
        assert "filter_huge_message_threshold" not in keys

    def test_used_in_history(self):
        """It IS actually used in _history.py for message filtering."""
        import code_muse.agents._history as hist

        source = hist.__file__
        with open(source) as f:
            content = f.read()
        assert "get_filter_huge_message_threshold" in content

    def test_default_value(self):
        """Default threshold is 50000."""
        from code_muse.config.parser import get_filter_huge_message_threshold

        with patch("code_muse.config.parser.get_value", return_value=None):
            assert get_filter_huge_message_threshold() == 50000


# ---------------------------------------------------------------------------
# Gap 7: max_loop_iterations safety cap in _runtime.py
# ---------------------------------------------------------------------------


class TestMaxLoopIterationsSafetyCap:
    """The hardcoded max_loop_iterations=50 safety cap in _runtime.py."""

    def test_safety_cap_exists(self):
        """The safety cap constant exists."""
        source = _runtime.__file__
        with open(source) as f:
            content = f.read()
        assert "max_loop_iterations = 50" in content

    def test_safety_cap_is_used_in_loop(self):
        """The cap is used as the loop range."""
        source = _runtime.__file__
        with open(source) as f:
            content = f.read()
        assert "for _ in range(max_loop_iterations):" in content

    def test_separate_retry_budgets_exist(self):
        """Both hook and critic retry budgets are read from config."""
        source = _runtime.__file__
        with open(source) as f:
            content = f.read()
        assert "get_max_hook_retries()" in content
        assert "get_max_critic_retries()" in content

    def test_both_exhausted_check_prevents_loop(self):
        """The loop breaks when both budgets are exhausted, not just one."""
        source = _runtime.__file__
        with open(source) as f:
            content = f.read()
        assert "both_exhausted" in content
