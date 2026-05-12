"""Sample eval: memory planning — assert save_memory usage."""

from code_muse.evals.eval_helpers import assert_tool_called, assert_tool_not_called
from code_muse.evals.eval_runner import EvalResult, run_eval


def eval_memory_fidelity() -> EvalResult:
    return run_eval(
        name="memory_fidelity_save",
        prompt="Save this important fact: the project uses Python 3.12",
        setup_files=None,
        assert_fn=lambda rig: assert_tool_called(rig, "save_memory"),
    )


def eval_memory_planning_important_info() -> EvalResult:
    return run_eval(
        name="memory_planning_important_info",
        prompt="You just discovered the project uses Django 5.0. Please remember that.",
        setup_files={"project_info.txt": "Framework: Django 5.0\n"},
        assert_fn=lambda rig: assert_tool_called(rig, "save_memory"),
    )


def eval_memory_planning_trivial_observation() -> EvalResult:
    return run_eval(
        name="memory_planning_trivial_observation",
        prompt="The sky is blue today. Do not save this observation.",
        setup_files=None,
        assert_fn=lambda rig: assert_tool_not_called(rig, "save_memory"),
    )
