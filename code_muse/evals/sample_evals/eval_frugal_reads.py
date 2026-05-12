"""Sample eval: frugal reads — assert that the agent reads files efficiently."""

from code_muse.evals.eval_helpers import (
    assert_read_is_ranged,
    assert_tool_called,
    assert_tool_not_called,
)
from code_muse.evals.eval_runner import EvalResult, TestRig, run_eval


def _assert_grep_then_ranged_read(rig: TestRig) -> tuple[bool, str]:
    grep_ok, grep_msg = assert_tool_called(rig, "grep")
    read_ok, read_msg = assert_read_is_ranged(rig)
    if grep_ok and read_ok:
        return True, f"{grep_msg} and {read_msg}"
    return False, f"{grep_msg}; {read_msg}"


def _assert_list_files_no_reads(rig: TestRig) -> tuple[bool, str]:
    list_ok, list_msg = assert_tool_called(rig, "list_files")
    no_read_ok, no_read_msg = assert_tool_not_called(rig, "read_file")
    if list_ok and no_read_ok:
        return True, f"{list_msg}; {no_read_msg}"
    return False, f"{list_msg}; {no_read_msg}"


def eval_frugal_reads_large_file() -> EvalResult:
    big_content = "\n".join(f"line {i}" for i in range(1, 501))
    return run_eval(
        name="frugal_reads_large_file",
        prompt="Read the large file and tell me the first 5 lines",
        setup_files={"big_file.txt": big_content},
        assert_fn=lambda rig: assert_read_is_ranged(rig),
    )


def eval_frugal_reads_search_before_read() -> EvalResult:
    big_content = "\n".join(f"line {i}" for i in range(1, 501))
    big_content += "\nTODO: fix this thing\n"
    return run_eval(
        name="frugal_reads_search_before_read",
        prompt="Find the TODO in big_file.txt and show me that line",
        setup_files={"big_file.txt": big_content},
        assert_fn=lambda rig: _assert_grep_then_ranged_read(rig),
    )


def eval_frugal_reads_list_patterns() -> EvalResult:
    return run_eval(
        name="frugal_reads_list_patterns",
        prompt="List the Python files in the src directory",
        setup_files={
            "src/__init__.py": "",
            "src/main.py": "print('hello')",
            "src/utils.py": "def helper(): pass",
            "src/README.md": "# Readme",
        },
        assert_fn=lambda rig: _assert_list_files_no_reads(rig),
    )
