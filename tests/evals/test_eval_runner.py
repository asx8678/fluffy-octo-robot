"""Tests for the eval runner core infrastructure."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from code_muse.evals.eval_runner import (
    EvalResult,
    EvalSuite,
    TestRig,
    ToolCall,
    _parse_tool_calls_from_stdout,
    run_all_evals,
    run_eval,
)


class TestToolCall:
    def test_tool_call_creation(self):
        tc = ToolCall(
            tool_name="read_file",
            tool_args={"file_path": "x.py"},
            result="ok",
            timestamp=1.0,
        )
        assert tc.tool_name == "read_file"
        assert tc.tool_args == {"file_path": "x.py"}
        assert tc.result == "ok"
        assert tc.timestamp == 1.0


class TestTestRig:
    def test_init_empty(self):
        rig = TestRig()
        assert rig.get_tool_logs() == []

    def test_record_and_get(self):
        rig = TestRig()
        rig.record_tool_call("a", {"x": 1}, "r1")
        rig.record_tool_call("b", {"y": 2}, "r2")
        logs = rig.get_tool_logs()
        assert len(logs) == 2
        assert logs[0].tool_name == "a"
        assert logs[1].tool_name == "b"

    def test_get_tool_logs_returns_copy(self):
        rig = TestRig()
        rig.record_tool_call("a", {}, None)
        logs = rig.get_tool_logs()
        logs.clear()
        assert len(rig.get_tool_logs()) == 1

    def test_get_by_name(self):
        rig = TestRig()
        rig.record_tool_call("grep", {"s": "foo"}, "r1")
        rig.record_tool_call("read_file", {"p": "bar"}, "r2")
        rig.record_tool_call("grep", {"s": "baz"}, "r3")
        assert len(rig.get_tool_calls_by_name("grep")) == 2
        assert len(rig.get_tool_calls_by_name("read_file")) == 1
        assert len(rig.get_tool_calls_by_name("missing")) == 0


class TestParseToolCalls:
    def test_parse_json_lines(self):
        line = json.dumps(
            {"tool_name": "t", "tool_args": {"a": 1}, "result": "ok", "timestamp": 1.0}
        )
        calls = _parse_tool_calls_from_stdout(line)
        assert len(calls) == 1
        assert calls[0].tool_name == "t"

    def test_parse_embedded_json(self):
        stdout = 'some prefix {"tool_name": "t", "tool_args": {"a": 1}} suffix'
        calls = _parse_tool_calls_from_stdout(stdout)
        assert len(calls) == 1
        assert calls[0].tool_name == "t"

    def test_ignores_malformed_json(self):
        calls = _parse_tool_calls_from_stdout("not json\n{tool_name: t}")
        assert calls == []

    def test_ignores_json_without_tool_fields(self):
        line = json.dumps({"foo": "bar"})
        calls = _parse_tool_calls_from_stdout(line)
        assert calls == []


class TestRunEval:
    def test_run_eval_success(self):
        def _assert_fn(rig: TestRig) -> tuple[bool, str]:
            return True, "all good"

        mock_stdout = json.dumps(
            {"tool_name": "list_files", "tool_args": {"directory": "."}, "result": "[]"}
        )
        mock_proc = MagicMock()
        mock_proc.stdout = mock_stdout
        mock_proc.stderr = ""

        with patch(
            "code_muse.evals.eval_runner.subprocess.run", return_value=mock_proc
        ):
            result = run_eval(
                name="test_eval",
                prompt="hello",
                setup_files={"a.txt": "hi"},
                assert_fn=_assert_fn,
            )

        assert isinstance(result, EvalResult)
        assert result.name == "test_eval"
        assert result.passed is True
        assert result.message == "all good"
        assert len(result.tool_logs) == 2  # _eval_output + list_files

    def test_run_eval_failure(self):
        def _assert_fn(rig: TestRig) -> tuple[bool, str]:
            return False, "missing tool"

        mock_proc = MagicMock()
        mock_proc.stdout = ""
        mock_proc.stderr = ""

        with patch(
            "code_muse.evals.eval_runner.subprocess.run", return_value=mock_proc
        ):
            result = run_eval(
                name="test_eval_fail",
                prompt="hello",
                setup_files=None,
                assert_fn=_assert_fn,
            )

        assert result.passed is False
        assert result.message == "missing tool"

    def test_run_eval_exception(self):
        def _assert_fn(rig: TestRig) -> tuple[bool, str]:
            raise RuntimeError("boom")

        mock_proc = MagicMock()
        mock_proc.stdout = ""
        mock_proc.stderr = ""

        with patch(
            "code_muse.evals.eval_runner.subprocess.run", return_value=mock_proc
        ):
            result = run_eval(
                name="test_eval_exc",
                prompt="hello",
                setup_files=None,
                assert_fn=_assert_fn,
            )

        assert result.passed is False
        assert "boom" in result.message


class TestEvalSuite:
    def test_add_and_run(self):
        suite = EvalSuite()
        suite.add("e1", "p1", {"f.txt": "c"}, lambda rig: (True, "ok"))
        suite.add("e2", "p2", None, lambda rig: (False, "nope"))

        mock_proc = MagicMock()
        mock_proc.stdout = ""
        mock_proc.stderr = ""

        with patch(
            "code_muse.evals.eval_runner.subprocess.run", return_value=mock_proc
        ):
            results = suite.run_all()

        assert len(results) == 2
        assert results[0].name == "e1"
        assert results[0].passed is True
        assert results[1].name == "e2"
        assert results[1].passed is False


class TestRunAllEvals:
    def test_run_all_evals_discovery(self, tmp_path: Path):
        # Create a fake eval file
        eval_file = tmp_path / "eval_dummy.py"
        eval_file.write_text(
            "from code_muse.evals.eval_runner import EvalResult\n"
            "def eval_dummy():\n"
            "    return EvalResult(name='dummy', passed=True, message='works')\n"
        )

        results = run_all_evals(tmp_path)
        assert len(results) == 1
        assert results[0].name == "dummy"
        assert results[0].passed is True

    def test_run_all_evals_empty_dir(self, tmp_path: Path):
        results = run_all_evals(tmp_path)
        assert results == []

    def test_run_all_evals_missing_dir(self, tmp_path: Path):
        missing = tmp_path / "nonexistent"
        results = run_all_evals(missing)
        assert results == []

    def test_run_all_evals_bad_function(self, tmp_path: Path):
        eval_file = tmp_path / "eval_bad.py"
        eval_file.write_text("def eval_bad():\n    raise ValueError('oops')\n")

        results = run_all_evals(tmp_path)
        assert len(results) == 1
        assert results[0].passed is False
        assert "oops" in results[0].message
