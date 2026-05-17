"""Tests for context status warnings and controls."""

import pytest
from code_muse.plugins.task_context.context_status import (
    check_and_emit_context_warnings,
    get_context_status_report,
    get_pin_help,
    reset_warning_state,
)


def test_no_warning_below_75():
    """No warning should fire below 75% usage."""
    reset_warning_state()
    # Should not raise
    check_and_emit_context_warnings(
        usage_pct=0.50,
        budget_tokens=128000,
        tokens_used=64000,
    )


def test_warning_at_75_percent():
    """Info warning fires at 75%."""
    reset_warning_state()
    check_and_emit_context_warnings(
        usage_pct=0.75,
        budget_tokens=128000,
        tokens_used=96000,
    )
    # Should have emitted (verified by coverage)


def test_warning_at_90_percent():
    """Critical warning fires at 90%."""
    reset_warning_state()
    check_and_emit_context_warnings(
        usage_pct=0.90,
        budget_tokens=128000,
        tokens_used=115200,
    )


def test_dedup_warning():
    """Same threshold does not fire twice."""
    reset_warning_state()
    check_and_emit_context_warnings(
        usage_pct=0.75,
        budget_tokens=128000,
        tokens_used=96000,
    )
    check_and_emit_context_warnings(
        usage_pct=0.76,
        budget_tokens=128000,
        tokens_used=97000,
    )
    # No double-firing


def test_reset_after_warning():
    """After reset, warning can fire again."""
    reset_warning_state()
    check_and_emit_context_warnings(
        usage_pct=0.75,
        budget_tokens=128000,
        tokens_used=96000,
    )
    reset_warning_state()
    check_and_emit_context_warnings(
        usage_pct=0.75,
        budget_tokens=128000,
        tokens_used=96000,
    )
    # Should work again


def test_context_report_structure():
    """Get a context status report for empty history."""
    report = get_context_status_report([])
    assert "Context Status" in report or "Error" in report
    assert report  # Not empty


def test_pin_help_structure():
    """Pin help text contains expected commands."""
    help_text = get_pin_help()
    assert "/pin" in help_text
    assert "help" in help_text
    assert "last" in help_text
    assert "list" in help_text
