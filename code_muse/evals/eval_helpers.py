"""Assertion helpers for the Behavioral Eval Framework.

Each helper inspects a :class:`TestRig` and returns ``(passed, message)``.
"""

from code_muse.evals.eval_runner import TestRig


def assert_tool_called(
    rig: TestRig, tool_name: str, min_count: int = 1
) -> tuple[bool, str]:
    """Check that *tool_name* was called at least *min_count* times."""
    calls = rig.get_tool_calls_by_name(tool_name)
    if len(calls) >= min_count:
        return True, f"'{tool_name}' called {len(calls)} time(s) (≥ {min_count})"
    return (
        False,
        f"Expected '{tool_name}' to be called ≥ {min_count} time(s), got {len(calls)}",
    )


def assert_tool_not_called(rig: TestRig, tool_name: str) -> tuple[bool, str]:
    """Check that *tool_name* was never called."""
    calls = rig.get_tool_calls_by_name(tool_name)
    if not calls:
        return True, f"'{tool_name}' was not called"
    return (
        False,
        f"Expected '{tool_name}' to not be called, got {len(calls)} call(s)",
    )


def assert_shell_has_flag(rig: TestRig, flag: str) -> tuple[bool, str]:
    """Check that shell commands include a specific flag (e.g. ``--silent``)."""
    shell_calls = rig.get_tool_calls_by_name("agent_run_shell_command")
    for tc in shell_calls:
        command = tc.tool_args.get("command", "")
        if flag in command:
            return True, f"Shell command contains flag '{flag}'"
    return (
        False,
        f"No shell command contained flag '{flag}' among {len(shell_calls)} call(s)",
    )


def assert_read_is_ranged(rig: TestRig) -> tuple[bool, str]:
    """Check that ``read_file`` calls use ``start_line``/``num_lines``."""
    read_calls = rig.get_tool_calls_by_name("read_file")
    if not read_calls:
        return False, "No 'read_file' calls observed"

    ranged = 0
    for tc in read_calls:
        if (
            tc.tool_args.get("start_line") is not None
            or tc.tool_args.get("num_lines") is not None
        ):
            ranged += 1

    if ranged == len(read_calls):
        return True, f"All {len(read_calls)} 'read_file' call(s) used range parameters"
    return (
        False,
        f"Only {ranged}/{len(read_calls)} 'read_file' call(s) used range parameters",
    )


def assert_output_contains(rig: TestRig, text: str) -> tuple[bool, str]:
    """Check that the combined stdout/stderr captured during the eval contains *text*.

    Note: This helper requires that the :class:`TestRig` was populated
    with a synthetic ``output`` tool call by :func:`run_eval` (the
    framework injects one when a ``_raw_output`` key is present).
    """
    output_calls = rig.get_tool_calls_by_name("_eval_output")
    if not output_calls:
        return False, "No eval output captured (internal)"
    combined = output_calls[0].result or ""
    if text in combined:
        return True, f"Output contains '{text}'"
    return False, f"Output does not contain '{text}'"
