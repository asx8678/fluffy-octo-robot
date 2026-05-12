"""Behavioral Eval Framework for Muse.

Standalone test framework for evaluating agent behavior through
subprocess-based end-to-end testing with tool-call assertions.
"""

from code_muse.evals.eval_helpers import (
    assert_output_contains,
    assert_read_is_ranged,
    assert_shell_has_flag,
    assert_tool_called,
    assert_tool_not_called,
)
from code_muse.evals.eval_runner import (
    EvalResult,
    EvalSuite,
    TestRig,
    ToolCall,
    run_all_evals,
    run_eval,
)

__all__ = [
    "ToolCall",
    "TestRig",
    "EvalResult",
    "run_eval",
    "run_all_evals",
    "EvalSuite",
    "assert_tool_called",
    "assert_tool_not_called",
    "assert_shell_has_flag",
    "assert_read_is_ranged",
    "assert_output_contains",
]
