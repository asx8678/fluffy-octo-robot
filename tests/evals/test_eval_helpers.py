"""Tests for eval assertion helpers."""

from code_muse.evals.eval_helpers import (
    assert_output_contains,
    assert_read_is_ranged,
    assert_shell_has_flag,
    assert_tool_called,
    assert_tool_not_called,
)
from code_muse.evals.eval_runner import TestRig


class TestAssertToolCalled:
    def test_passes_when_called(self):
        rig = TestRig()
        rig.record_tool_call("grep", {"s": "foo"}, "ok")
        passed, msg = assert_tool_called(rig, "grep")
        assert passed is True
        assert "called 1 time(s)" in msg

    def test_passes_with_min_count(self):
        rig = TestRig()
        rig.record_tool_call("grep", {"s": "a"}, "ok")
        rig.record_tool_call("grep", {"s": "b"}, "ok")
        passed, msg = assert_tool_called(rig, "grep", min_count=2)
        assert passed is True
        assert "called 2 time(s)" in msg

    def test_fails_when_not_called(self):
        rig = TestRig()
        passed, msg = assert_tool_called(rig, "grep")
        assert passed is False
        assert "got 0" in msg

    def test_fails_when_below_min_count(self):
        rig = TestRig()
        rig.record_tool_call("grep", {"s": "a"}, "ok")
        passed, msg = assert_tool_called(rig, "grep", min_count=2)
        assert passed is False
        assert "got 1" in msg


class TestAssertToolNotCalled:
    def test_passes_when_absent(self):
        rig = TestRig()
        passed, msg = assert_tool_not_called(rig, "delete_file")
        assert passed is True
        assert "not called" in msg

    def test_fails_when_present(self):
        rig = TestRig()
        rig.record_tool_call("delete_file", {"path": "x"}, "ok")
        passed, msg = assert_tool_not_called(rig, "delete_file")
        assert passed is False
        assert "got 1 call(s)" in msg


class TestAssertShellHasFlag:
    def test_passes_when_flag_present(self):
        rig = TestRig()
        rig.record_tool_call(
            "agent_run_shell_command", {"command": "npm install --silent"}, "ok"
        )
        passed, msg = assert_shell_has_flag(rig, "--silent")
        assert passed is True
        assert "contains flag '--silent'" in msg

    def test_fails_when_flag_missing(self):
        rig = TestRig()
        rig.record_tool_call(
            "agent_run_shell_command", {"command": "npm install"}, "ok"
        )
        passed, msg = assert_shell_has_flag(rig, "--silent")
        assert passed is False
        assert "No shell command contained flag '--silent'" in msg

    def test_fails_when_no_shell_calls(self):
        rig = TestRig()
        passed, msg = assert_shell_has_flag(rig, "--silent")
        assert passed is False
        assert "No shell command contained flag '--silent'" in msg


class TestAssertReadIsRanged:
    def test_passes_when_all_ranged(self):
        rig = TestRig()
        rig.record_tool_call(
            "read_file", {"file_path": "a.py", "start_line": 1, "num_lines": 10}, "ok"
        )
        passed, msg = assert_read_is_ranged(rig)
        assert passed is True
        assert "All 1 'read_file' call(s) used range parameters" in msg

    def test_fails_when_no_read_calls(self):
        rig = TestRig()
        passed, msg = assert_read_is_ranged(rig)
        assert passed is False
        assert "No 'read_file' calls observed" in msg

    def test_fails_when_some_unranged(self):
        rig = TestRig()
        rig.record_tool_call("read_file", {"file_path": "a.py"}, "ok")
        rig.record_tool_call("read_file", {"file_path": "b.py", "start_line": 1}, "ok")
        passed, msg = assert_read_is_ranged(rig)
        assert passed is False
        assert "Only 1/2 'read_file' call(s) used range parameters" in msg


class TestAssertOutputContains:
    def test_passes_when_text_present(self):
        rig = TestRig()
        rig.record_tool_call("_eval_output", {}, "hello world")
        passed, msg = assert_output_contains(rig, "world")
        assert passed is True
        assert "Output contains 'world'" in msg

    def test_fails_when_text_missing(self):
        rig = TestRig()
        rig.record_tool_call("_eval_output", {}, "hello")
        passed, msg = assert_output_contains(rig, "world")
        assert passed is False
        assert "Output does not contain 'world'" in msg

    def test_fails_when_no_output_record(self):
        rig = TestRig()
        passed, msg = assert_output_contains(rig, "world")
        assert passed is False
        assert "No eval output captured" in msg
