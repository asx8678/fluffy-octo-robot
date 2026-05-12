"""Tests for test compression strategies."""

import json

from code_muse.plugins.filter_engine.strategies.test import (
    compress_cargo_test,
    compress_pytest,
    compress_test,
    compress_vitest_jest,
)

from code_muse.plugins.filter_engine.verbosity import VerbosityLevel


class TestPytest:
    """pytest output compression."""

    SAMPLE = (
        "tests/test_x.py::test_foo PASSED\n"
        "tests/test_x.py::test_bar FAILED\n"
        "tests/test_x.py::test_baz SKIPPED\n"
        "tests/test_x.py::test_qux PASSED\n"
        "\n"
        "= 2 passed, 1 failed, 1 skipped in 0.5s =\n"
    )

    def test_compact_shows_failures_and_summary(self) -> None:
        out = compress_pytest(self.SAMPLE, "", VerbosityLevel.COMPACT)
        assert "FAILED" in out.stdout
        assert "= 2 passed, 1 failed, 1 skipped in 0.5s =" in out.stdout

    def test_compact_hides_passes(self) -> None:
        out = compress_pytest(self.SAMPLE, "", VerbosityLevel.COMPACT)
        # Pass lines should NOT appear in compact mode (only failures + summary)
        lines = [line for line in out.stdout.splitlines() if "PASSED" in line]
        assert len(lines) == 0

    def test_verbose_shows_all(self) -> None:
        out = compress_pytest(self.SAMPLE, "", VerbosityLevel.VERBOSE)
        assert "PASSED" in out.stdout
        assert "FAILED" in out.stdout
        assert "SKIPPED" in out.stdout

    def test_no_failures_shows_summary(self) -> None:
        sample = "tests/test_x.py::test_foo PASSED\n= 1 passed in 0.2s =\n"
        out = compress_pytest(sample, "", VerbosityLevel.COMPACT)
        assert "= 1 passed in 0.2s =" in out.stdout


class TestVitestJest:
    """vitest / jest output compression."""

    TEXT_SAMPLE = (
        "PASS src/utils.test.ts\n"
        "FAIL src/core.test.ts\n"
        "  ✕ should compute correctly\n"
        "\n"
        "Test Suites: 1 failed, 1 passed, 2 total\n"
        "Tests:       1 failed, 2 passed, 3 total\n"
    )

    def test_text_compact_shows_failures(self) -> None:
        out = compress_vitest_jest(self.TEXT_SAMPLE, "", VerbosityLevel.COMPACT)
        assert "FAIL" in out.stdout
        assert "Tests:" in out.stdout

    def test_text_verbose_shows_all(self) -> None:
        out = compress_vitest_jest(self.TEXT_SAMPLE, "", VerbosityLevel.VERBOSE)
        assert out.stdout == self.TEXT_SAMPLE

    def test_json_parsing(self) -> None:
        data = {
            "testResults": [
                {
                    "assertionResults": [
                        {"status": "passed", "title": "foo"},
                        {"status": "failed", "title": "bar"},
                    ]
                }
            ]
        }
        out = compress_vitest_jest(json.dumps(data), "", VerbosityLevel.COMPACT)
        assert "2 tests" in out.stdout
        assert "1 passed" in out.stdout
        assert "1 failed" in out.stdout
        assert "FAIL bar" in out.stdout


class TestCargoTest:
    """cargo test output compression."""

    TEXT_SAMPLE = (
        "running 3 tests\n"
        "test test_foo ... ok\n"
        "test test_bar ... FAILED\n"
        "test test_baz ... ok\n"
        "\n"
        "test result: FAILED. 2 passed; 1 failed\n"
    )

    def test_text_compact_shows_failures_and_summary(self) -> None:
        out = compress_cargo_test(self.TEXT_SAMPLE, "", VerbosityLevel.COMPACT)
        assert "FAILED" in out.stdout
        assert "test result:" in out.stdout

    def test_text_verbose_shows_all(self) -> None:
        out = compress_cargo_test(self.TEXT_SAMPLE, "", VerbosityLevel.VERBOSE)
        assert out.stdout == self.TEXT_SAMPLE

    def test_ndjson_parsing(self) -> None:
        ndjson = (
            '{"event":"started","name":"foo"}\n'
            '{"event":"ok","name":"foo"}\n'
            '{"event":"started","name":"bar"}\n'
            '{"event":"failed","name":"bar"}\n'
        )
        out = compress_cargo_test(ndjson, "", VerbosityLevel.COMPACT)
        assert "2 tests" in out.stdout
        assert "1 passed" in out.stdout
        assert "1 failed" in out.stdout


class TestTestDispatcher:
    """Main test dispatcher routing."""

    def test_pytest_route(self) -> None:
        out = compress_test("pytest", "a::b PASSED\n", "", 0, VerbosityLevel.COMPACT)
        assert out is not None
        assert "PASSED" in out.stdout or "= 1 passed" in out.stdout

    def test_jest_route(self) -> None:
        out = compress_test("jest", "PASS\n", "", 0, VerbosityLevel.COMPACT)
        assert out is not None

    def test_cargo_route(self) -> None:
        out = compress_test(
            "cargo test", "test a ... ok\n", "", 0, VerbosityLevel.COMPACT
        )
        assert out is not None

    def test_generic_fallback(self) -> None:
        out = compress_test(
            "mvn test", "BUILD FAILURE\n", "", 1, VerbosityLevel.COMPACT
        )
        assert out is not None
        assert "BUILD FAILURE" in out.stdout
