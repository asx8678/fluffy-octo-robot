"""Tests for new config keys (budget thresholds, dependency overlap)."""

from code_muse.plugins.task_context.config import (
    get_task_budget_critical_at,
    get_task_budget_warn_at,
    get_task_config_summary,
    get_task_dependency_file_overlap,
    set_task_budget_critical_at,
    set_task_budget_warn_at,
    set_task_dependency_file_overlap,
)


class TestBudgetWarnAt:
    def test_default(self):
        val = get_task_budget_warn_at()
        assert val == 0.65

    def test_set_and_get(self):
        set_task_budget_warn_at(0.5)
        assert get_task_budget_warn_at() == 0.5

    def test_clamped_low(self):
        set_task_budget_warn_at(0.1)
        assert get_task_budget_warn_at() == 0.3

    def test_clamped_high(self):
        set_task_budget_warn_at(1.5)
        assert get_task_budget_warn_at() == 0.95


class TestBudgetCriticalAt:
    def test_default(self):
        val = get_task_budget_critical_at()
        assert val == 0.85

    def test_set_and_get(self):
        set_task_budget_critical_at(0.75)
        assert get_task_budget_critical_at() == 0.75

    def test_clamped_low(self):
        set_task_budget_critical_at(0.2)
        assert get_task_budget_critical_at() == 0.5

    def test_clamped_high(self):
        set_task_budget_critical_at(1.5)
        assert get_task_budget_critical_at() == 0.99


class TestDependencyFileOverlap:
    def test_default(self):
        val = get_task_dependency_file_overlap()
        assert val == 2

    def test_set_and_get(self):
        set_task_dependency_file_overlap(5)
        assert get_task_dependency_file_overlap() == 5

    def test_clamped_low(self):
        set_task_dependency_file_overlap(0)
        assert get_task_dependency_file_overlap() == 1

    def test_clamped_high(self):
        set_task_dependency_file_overlap(100)
        assert get_task_dependency_file_overlap() == 20


class TestConfigSummary:
    def test_includes_new_keys(self):
        summary = get_task_config_summary()
        assert "Budget warn at" in summary
        assert "Budget critical at" in summary
        assert "Dependency file overlap" in summary
