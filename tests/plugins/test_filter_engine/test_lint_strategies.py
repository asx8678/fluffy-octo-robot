"""Tests for lint compression strategies."""

import json

from code_muse.plugins.filter_engine.strategies.lint import (
    compress_eslint,
    compress_find,
    compress_golangci,
    compress_grep,
    compress_lint,
    compress_ruff,
)

from code_muse.plugins.filter_engine.verbosity import VerbosityLevel


class TestRuff:
    """ruff output compression."""

    TEXT_SAMPLE = (
        "file.py:5:1: E501 Line too long (120 > 88)\n"
        "file.py:10:1: F841 Unused variable 'x'\n"
        "other.py:3:1: E501 Line too long (100 > 88)\n"
        "other.py:7:1: E501 Line too long (95 > 88)\n"
    )

    def test_text_grouping(self) -> None:
        out = compress_ruff(self.TEXT_SAMPLE, "", VerbosityLevel.COMPACT)
        assert "E501: 2 files, 3 occurrences" in out.stdout
        assert "F841: 1 files, 1 occurrences" in out.stdout

    def test_verbose_includes_files(self) -> None:
        out = compress_ruff(self.TEXT_SAMPLE, "", VerbosityLevel.VERBOSE)
        assert "file.py" in out.stdout

    def test_json_mode(self) -> None:
        data = [
            {"code": "E501", "filename": "a.py"},
            {"code": "E501", "filename": "b.py"},
            {"code": "F401", "filename": "a.py"},
        ]
        out = compress_ruff(json.dumps(data), "", VerbosityLevel.COMPACT)
        assert "E501: 2 files, 2 occurrences" in out.stdout
        assert "F401: 1 files, 1 occurrences" in out.stdout

    def test_no_issues(self) -> None:
        out = compress_ruff("", "", VerbosityLevel.COMPACT)
        assert "No issues found" in out.stdout


class TestEslint:
    """eslint output compression."""

    TEXT_SAMPLE = (
        "src/a.js:5:3: error Something wrong [rule-a]\n"
        "src/b.js:10:1: warning Deprecated [rule-b]\n"
        "src/a.js:20:5: error Another issue [rule-c]\n"
    )

    def test_text_grouping(self) -> None:
        out = compress_eslint(self.TEXT_SAMPLE, "", VerbosityLevel.COMPACT)
        assert "error:rule-a: 1 files, 1 occurrences" in out.stdout
        assert "warning:rule-b: 1 files, 1 occurrences" in out.stdout
        assert "error:rule-c: 1 files, 1 occurrences" in out.stdout

    def test_json_mode(self) -> None:
        data = [
            {
                "filePath": "a.js",
                "messages": [
                    {"severity": 2, "ruleId": "rule-a"},
                    {"severity": 1, "ruleId": "rule-b"},
                ],
            }
        ]
        out = compress_eslint(json.dumps(data), "", VerbosityLevel.COMPACT)
        assert "error:rule-a: 1 files, 1 occurrences" in out.stdout
        assert "warning:rule-b: 1 files, 1 occurrences" in out.stdout


class TestGolangci:
    """golangci-lint output compression."""

    TEXT_SAMPLE = (
        "main.go:5:3: unusedParam unused parameter 'ctx' (unused-param)\n"
        "pkg/util.go:10:1: lineLength line is 120 characters (line-length)\n"
        "main.go:20:5: shadowDecl variable 'err' shadows declaration (shadow)\n"
    )

    def test_text_grouping(self) -> None:
        out = compress_golangci(self.TEXT_SAMPLE, "", VerbosityLevel.COMPACT)
        assert "unused-param: 1 files, 1 occurrences" in out.stdout
        assert "line-length: 1 files, 1 occurrences" in out.stdout
        assert "shadow: 1 files, 1 occurrences" in out.stdout

    def test_json_mode(self) -> None:
        data = {
            "Issues": [
                {"FromLinter": "unused-param", "Pos": {"Filename": "a.go"}},
                {"FromLinter": "unused-param", "Pos": {"Filename": "b.go"}},
                {"FromLinter": "shadow", "Pos": {"Filename": "a.go"}},
            ]
        }
        out = compress_golangci(json.dumps(data), "", VerbosityLevel.COMPACT)
        assert "unused-param: 2 files, 2 occurrences" in out.stdout
        assert "shadow: 1 files, 1 occurrences" in out.stdout


class TestGrep:
    """grep / rg output compression."""

    SAMPLE = (
        "src/core.py:10:def foo():\n"
        "src/core.py:25:def bar():\n"
        "src/utils.py:5:import os\n"
    )

    def test_grouping_by_file(self) -> None:
        out = compress_grep(self.SAMPLE, "", VerbosityLevel.COMPACT)
        assert "src/core.py: 2 matches" in out.stdout
        assert "src/utils.py: 1 matches" in out.stdout

    def test_verbose_includes_matches(self) -> None:
        out = compress_grep(self.SAMPLE, "", VerbosityLevel.VERBOSE)
        assert "def foo()" in out.stdout

    def test_no_matches(self) -> None:
        out = compress_grep("", "", VerbosityLevel.COMPACT)
        assert "No matches" in out.stdout


class TestFind:
    """find output compression."""

    SAMPLE = "./src/core.py\n./src/utils.py\n./tests/test_core.py\n./docs/\n"

    def test_grouping_by_dir(self) -> None:
        out = compress_find(self.SAMPLE, "", VerbosityLevel.COMPACT)
        assert "./src: 2 files" in out.stdout
        assert "./tests: 1 files" in out.stdout
        assert "./docs: " in out.stdout

    def test_no_results(self) -> None:
        out = compress_find("", "", VerbosityLevel.COMPACT)
        assert "No results" in out.stdout


class TestLintDispatcher:
    """Main lint dispatcher routing."""

    def test_ruff_route(self) -> None:
        out = compress_lint(
            "ruff check .", "a.py:1:1: E501\n", "", 0, VerbosityLevel.COMPACT
        )
        assert out is not None
        assert "E501" in out.stdout

    def test_grep_route(self) -> None:
        out = compress_lint(
            "grep def .", "a.py:1:def foo\n", "", 0, VerbosityLevel.COMPACT
        )
        assert out is not None
        assert "a.py" in out.stdout

    def test_generic_fallback(self) -> None:
        out = compress_lint(
            "custom-linter", "ERROR: bad\n", "", 1, VerbosityLevel.COMPACT
        )
        assert out is not None
