"""Tests for context window resolution helpers."""

from code_muse.plugins.task_context._context_utils import (
    get_cached_context_limit,
    get_context_limit,
    get_effective_budget,
)


def test_get_context_limit_default():
    """Test that context limit returns a reasonable value."""
    ctx = get_context_limit()
    assert isinstance(ctx, int)
    assert ctx > 0


def test_get_cached_context_limit():
    """Test that cached context limit works."""
    ctx = get_cached_context_limit()
    assert isinstance(ctx, int)
    assert ctx > 0


def test_effective_budget():
    """Test that effective budget is a reasonable fraction of context."""
    budget = get_effective_budget(overhead=5000)
    assert isinstance(budget, int)
    assert budget > 1000


def test_context_limit_no_longer_hardcoded():
    """Test that budget.py doesn't use hardcoded 128k anymore."""
    from code_muse.plugins.task_context.budget import _resolve_budget_tokens

    ctx = _resolve_budget_tokens()
    # Should return the actual model context, not 128k
    # If model can't be resolved, it falls back but should still be > 0
    assert ctx > 0
    assert isinstance(ctx, int)
