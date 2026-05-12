"""Sample eval: shell efficiency — assert that the agent uses efficient shell flags."""

from code_muse.evals.eval_helpers import assert_shell_has_flag
from code_muse.evals.eval_runner import EvalResult, TestRig, run_eval


def _assert_shell_has_quiet_flag(rig: TestRig) -> tuple[bool, str]:
    for flag in ("--quiet", "-q"):
        passed, msg = assert_shell_has_flag(rig, flag)
        if passed:
            return True, msg
    return False, "No shell command contained quiet flag '--quiet' or '-q'"


def eval_shell_efficiency_npm_install() -> EvalResult:
    return run_eval(
        name="shell_efficiency_npm_install",
        prompt="Run 'npm install express' and tell me what happened",
        setup_files={"package.json": '{"name": "test"}'},
        assert_fn=lambda rig: assert_shell_has_flag(rig, "--silent"),
    )


def eval_shell_efficiency_git_clone() -> EvalResult:
    return run_eval(
        name="shell_efficiency_git_clone",
        prompt="Clone the code-muse repository so we can inspect it",
        setup_files=None,
        assert_fn=lambda rig: assert_shell_has_flag(rig, "--depth 1"),
    )


def eval_shell_efficiency_pip_install() -> EvalResult:
    return run_eval(
        name="shell_efficiency_pip_install",
        prompt="Install the requests package using pip",
        setup_files={"requirements.txt": "requests\n"},
        assert_fn=lambda rig: _assert_shell_has_quiet_flag(rig),
    )
