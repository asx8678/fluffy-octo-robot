"""Tests for model-aware budget warnings."""

from code_muse.plugins.task_context.budget import (
    _resolve_budget_tokens,
    check_and_warn,
    estimate_current_budget,
    reset_warning_flags,
)


def test_resolve_budget_minimum():
    """Test that resolved budget is at least 4096."""
    ctx = _resolve_budget_tokens()
    assert ctx >= 4096


def test_estimate_budget_with_model_name():
    """Test estimate_current_budget with explicit model name."""
    budget = estimate_current_budget([], model_name="gpt-4o")
    assert budget["budget_tokens"] > 0
    assert budget["model_name"] == "gpt-4o"


def test_estimate_budget_no_model():
    """Test estimate_current_budget without model name."""
    budget = estimate_current_budget([])
    assert budget["budget_tokens"] > 0


def test_budget_includes_protected_facts():
    """Test that budget info includes protected fact details."""
    budget = estimate_current_budget([])
    assert "protected_facts_tokens" in budget
    assert "protected_facts" in budget


def test_check_and_warn_with_model():
    """Test check_and_warn with model_name parameter."""
    reset_warning_flags()
    budget_info = {
        "total_tokens": 5000,
        "budget_tokens": 128000,
        "usage_pct": 0.95,  # Above critical
        "remaining_tokens": 3000,
        "model_name": "claude-4-sonnet",
    }
    # Should not raise
    check_and_warn(
        budget_info, warn_at=0.65, critical_at=0.85, model_name="claude-4-sonnet"
    )
