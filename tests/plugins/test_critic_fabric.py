"""Tests for the Critic Fabric plugin.

Covers:
    1. Model construction, serialisation, and compatibility helpers
    2. Preflight rejects truncated / invalid code before any backend
    3. Preflight passes valid code through to the backend
    4. Backend registry (register, alias, lookup, errors)
    5. Fabric review() orchestrates preflight → backend
    6. code_critic.reviewer.review_code uses fabric preflight
    7. Golden truncation set — deterministic offline false-negative gate
"""

from __future__ import annotations

import asyncio
import textwrap
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from code_muse.plugins.critic_fabric.backends import (
    _REGISTRY,
    get_backend,
    list_backends,
    register_alias,
    register_backend,
)
from code_muse.plugins.critic_fabric.models import (
    CriticIssue,
    CriticRequest,
    CriticVerdict,
    VerdictKind,
)
from code_muse.plugins.critic_fabric.preflight import run_preflight

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run_async(coro: Any) -> Any:
    """Run an async coroutine synchronously in a fresh event loop."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ===================================================================
# 1. Models — construction and serialisation
# ===================================================================


class TestCriticIssue:
    """Tests for CriticIssue model."""

    def test_construction_defaults(self) -> None:
        issue = CriticIssue(message="bad code")
        assert issue.severity == "warning"
        assert issue.message == "bad code"
        assert issue.suggestion is None

    def test_construction_full(self) -> None:
        issue = CriticIssue(severity="critical", message="bug", suggestion="fix it")
        assert issue.severity == "critical"
        assert issue.suggestion == "fix it"

    def test_serialisation_roundtrip(self) -> None:
        issue = CriticIssue(severity="info", message="nit")
        data = issue.model_dump()
        restored = CriticIssue.model_validate(data)
        assert restored == issue


class TestCriticRequest:
    """Tests for CriticRequest model."""

    def test_construction_defaults(self) -> None:
        req = CriticRequest(file_path="foo.py", code_snippet="pass")
        assert req.operation == "review"
        assert req.agent_name == "unknown"
        assert req.backend == "code_critic"
        assert req.metadata == {}

    def test_construction_full(self) -> None:
        req = CriticRequest(
            file_path="bar.py",
            code_snippet="x = 1",
            operation="manual_review",
            agent_name="heavy-coding-agent",
            backend="heavy",
            metadata={"reasoning_summary": "test"},
        )
        assert req.backend == "heavy"
        assert req.metadata["reasoning_summary"] == "test"


class TestCriticVerdict:
    """Tests for CriticVerdict model."""

    def test_approved_verdict(self) -> None:
        v = CriticVerdict(verdict=VerdictKind.APPROVED, summary="looks good")
        assert v.verdict == VerdictKind.APPROVED
        assert v.issues == []
        assert v.preflight_rejected is False

    def test_rejected_verdict_preflight(self) -> None:
        v = CriticVerdict(
            verdict=VerdictKind.REJECTED,
            summary="truncated",
            issues=["SyntaxError at line 5"],
            suggestion="Rewrite the entire file",
            backend="preflight",
            preflight_rejected=True,
        )
        assert v.preflight_rejected is True
        assert v.backend == "preflight"

    def test_to_dict_contains_required_keys(self) -> None:
        v = CriticVerdict(
            verdict=VerdictKind.REJECTED,
            summary="bad",
            issues=["issue1"],
            suggestion="fix it",
        )
        d = v.to_dict()
        assert "verdict" in d
        assert "summary" in d
        assert "issues" in d
        assert "suggestion" in d
        assert d["verdict"] == "rejected"
        assert d["issues"] == ["issue1"]

    def test_to_dict_includes_raw_response(self) -> None:
        v = CriticVerdict(
            verdict=VerdictKind.APPROVED,
            summary="ok",
            raw_response="LLM text here",
        )
        d = v.to_dict()
        assert d["raw_response"] == "LLM text here"

    def test_to_dict_omits_raw_response_when_none(self) -> None:
        v = CriticVerdict(verdict=VerdictKind.APPROVED, summary="ok")
        d = v.to_dict()
        assert "raw_response" not in d

    def test_from_dict_basic(self) -> None:
        data = {
            "verdict": "approved",
            "summary": "clean",
            "issues": [],
            "suggestion": None,
        }
        v = CriticVerdict.from_dict(data, backend="test")
        assert v.verdict == VerdictKind.APPROVED
        assert v.backend == "test"

    def test_from_dict_unknown_verdict(self) -> None:
        data = {"verdict": "banana", "summary": "weird", "issues": []}
        v = CriticVerdict.from_dict(data)
        assert v.verdict == VerdictKind.FLAGGED

    def test_from_dict_missing_keys(self) -> None:
        data = {"verdict": "rejected"}
        v = CriticVerdict.from_dict(data, backend="x", preflight_rejected=True)
        assert v.verdict == VerdictKind.REJECTED
        assert v.summary == ""
        assert v.issues == []
        assert v.preflight_rejected is True

    def test_roundtrip_to_dict_from_dict(self) -> None:
        original = CriticVerdict(
            verdict=VerdictKind.REJECTED,
            summary="trunc",
            issues=["SyntaxError: ..."],
            suggestion="rewrite",
            backend="preflight",
            preflight_rejected=True,
        )
        restored = CriticVerdict.from_dict(original.to_dict(), backend="preflight")
        assert restored.verdict == original.verdict
        assert restored.summary == original.summary
        assert restored.issues == original.issues
        assert restored.suggestion == original.suggestion


class TestVerdictKind:
    """Tests for VerdictKind enum."""

    def test_values(self) -> None:
        assert VerdictKind.APPROVED == "approved"
        assert VerdictKind.REJECTED == "rejected"
        assert VerdictKind.FLAGGED == "flagged"
        assert VerdictKind.ERROR == "error"

    def test_from_string(self) -> None:
        assert VerdictKind("approved") is VerdictKind.APPROVED


# ===================================================================
# 2. Preflight — rejects truncated code
# ===================================================================


class TestPreflightRejectsTruncated:
    """Preflight must reject obviously truncated code."""

    def test_empty_string(self) -> None:
        result = run_preflight("", "test.py")
        assert result is not None
        assert result.verdict == VerdictKind.REJECTED
        assert result.preflight_rejected is True

    def test_whitespace_only(self) -> None:
        result = run_preflight("   \n  \t  ", "test.py")
        assert result is not None
        assert result.verdict == VerdictKind.REJECTED

    def test_python_syntax_error(self) -> None:
        code = "def foo(\n"  # unclosed paren
        result = run_preflight(code, "test.py")
        assert result is not None
        assert result.verdict == VerdictKind.REJECTED
        assert result.preflight_rejected is True
        assert "syntax" in result.summary.lower() or "truncat" in result.summary.lower()

    def test_python_incomplete(self) -> None:
        code = "def hello():\n    return\n"
        # This is valid Python — should pass
        result = run_preflight(code, "test.py")
        assert result is None

    def test_open_ending_brace(self) -> None:
        code = "function foo() {"
        result = run_preflight(code, "test.js")
        assert result is not None
        assert result.verdict == VerdictKind.REJECTED

    def test_truncated_declaration(self) -> None:
        code = "const x"
        result = run_preflight(code, "test.js")
        assert result is not None
        assert result.verdict == VerdictKind.REJECTED

    def test_bracket_imbalance(self) -> None:
        code = "{\n{\n{\n}\n}"  # 3 opens, 2 closes — with tolerance 2
        # Need more imbalance to trigger
        code = "{\n{\n{\n{\n{\n}\n}"  # 5 opens, 2 closes
        result = run_preflight(code, "test.rs")
        assert result is not None
        assert result.verdict == VerdictKind.REJECTED

    def test_trailing_ellipsis(self) -> None:
        code = "fn main() {\n    ...\n"
        result = run_preflight(code, "test.rs")
        assert result is not None
        assert result.verdict == VerdictKind.REJECTED


class TestPreflightPassesValid:
    """Preflight must pass valid code through to the backend."""

    def test_valid_python(self) -> None:
        code = textwrap.dedent("""\
            def hello():
                return "world"
        """)
        result = run_preflight(code, "app.py")
        assert result is None

    def test_valid_javascript(self) -> None:
        code = "function foo() { return 1; }\n"
        result = run_preflight(code, "app.js")
        assert result is None

    def test_valid_rust(self) -> None:
        code = 'fn main() { println!("hello"); }\n'
        result = run_preflight(code, "main.rs")
        assert result is None

    def test_non_code_file(self) -> None:
        """Non-code files without obvious truncation should pass."""
        code = "This is a markdown file.\n"
        result = run_preflight(code, "README.md")
        assert result is None

    def test_valid_json(self) -> None:
        code = '{"key": "value"}'
        result = run_preflight(code, "config.json")
        assert result is None


# ===================================================================
# 3. Backend registry
# ===================================================================


class TestBackendRegistry:
    """Tests for the backend registry."""

    def test_code_critic_builtin(self) -> None:
        backend = get_backend("code_critic")
        assert backend is not None
        assert callable(backend)

    def test_light_alias(self) -> None:
        backend = get_backend("light")
        assert backend is get_backend("code_critic")

    def test_heavy_alias(self) -> None:
        backend = get_backend("heavy")
        assert backend is get_backend("code_critic")

    def test_debate_builtin(self) -> None:
        backend = get_backend("debate")
        assert backend is not None

    def test_unknown_backend_raises(self) -> None:
        with pytest.raises(KeyError, match="Unknown critic backend"):
            get_backend("nonexistent_backend")

    def test_register_custom_backend(self) -> None:
        async def custom_backend(request: CriticRequest) -> CriticVerdict:
            return CriticVerdict(verdict=VerdictKind.APPROVED, summary="custom says ok")

        register_backend("__test_custom", custom_backend)
        assert get_backend("__test_custom") is custom_backend
        # Cleanup
        _REGISTRY.pop("__test_custom", None)

    def test_register_alias(self) -> None:
        register_alias("__test_alias", "code_critic")
        assert get_backend("__test_alias") is get_backend("code_critic")
        # Cleanup (aliases are in a module-level dict — no easy pop,
        # but the test is harmless since it just maps to code_critic)

    def test_list_backends_includes_builtins(self) -> None:
        names = list_backends()
        assert "code_critic" in names
        assert "light" in names
        assert "heavy" in names
        assert "debate" in names


# ===================================================================
# 4. Fabric review() — preflight → backend orchestration
# ===================================================================


class TestFabricReview:
    """Tests for the top-level fabric review() function."""

    def test_truncated_code_returns_preflight_verdict(self) -> None:
        """Truncated code never reaches the backend."""
        from code_muse.plugins.critic_fabric.fabric import review

        request = CriticRequest(
            file_path="test.py",
            code_snippet="def foo(",  # truncated
            backend="code_critic",
        )
        verdict = _run_async(review(request))
        assert verdict.verdict == VerdictKind.REJECTED
        assert verdict.preflight_rejected is True
        assert verdict.backend == "preflight"

    def test_valid_code_calls_backend(self) -> None:
        """Valid code is dispatched to the requested backend."""
        from code_muse.plugins.critic_fabric.fabric import review

        # Register a test backend that always approves
        async def _approve(request: CriticRequest) -> CriticVerdict:
            return CriticVerdict(
                verdict=VerdictKind.APPROVED,
                summary="test backend approved",
                backend="__test",
            )

        register_backend("__test_approve", _approve)

        request = CriticRequest(
            file_path="test.py",
            code_snippet="x = 1\n",
            backend="__test_approve",
        )
        verdict = _run_async(review(request))
        assert verdict.verdict == VerdictKind.APPROVED
        # Backend set its own name inside the verdict; fabric doesn't overwrite
        assert verdict.backend == "__test"

        # Cleanup
        _REGISTRY.pop("__test_approve", None)

    def test_unknown_backend_returns_error(self) -> None:
        """Requesting a nonexistent backend returns an error verdict."""
        from code_muse.plugins.critic_fabric.fabric import review

        request = CriticRequest(
            file_path="test.py",
            code_snippet="x = 1\n",
            backend="__nonexistent_for_test",
        )
        verdict = _run_async(review(request))
        assert verdict.verdict == VerdictKind.ERROR
        assert "Unknown" in verdict.summary

    def test_backend_exception_returns_error(self) -> None:
        """A backend that raises returns an error verdict, not an exception."""
        from code_muse.plugins.critic_fabric.fabric import review

        async def _boom(request: CriticRequest) -> CriticVerdict:
            raise RuntimeError("boom")

        register_backend("__test_boom", _boom)

        request = CriticRequest(
            file_path="test.py",
            code_snippet="x = 1\n",
            backend="__test_boom",
        )
        verdict = _run_async(review(request))
        assert verdict.verdict == VerdictKind.ERROR
        assert "boom" in verdict.summary

        # Cleanup
        _REGISTRY.pop("__test_boom", None)


# ===================================================================
# 5. code_critic.reviewer compatibility — uses fabric preflight
# ===================================================================


class TestCodeCriticReviewerCompat:
    """code_critic.reviewer.review_code should use fabric preflight."""

    def test_truncated_python_returns_rejected_dict(self) -> None:
        """Truncated Python code should be caught by preflight and return a
        dict with verdict='rejected' — no LLM call needed."""
        from code_muse.plugins.code_critic.reviewer import review_code

        result = _run_async(
            review_code(
                file_path="test.py",
                code_snippet="def foo(",  # truncated
            )
        )
        assert isinstance(result, dict)
        assert result["verdict"] == "rejected"
        assert "issues" in result
        assert "suggestion" in result

    def test_truncated_js_returns_rejected_dict(self) -> None:
        """Truncated JS code should be caught by preflight."""
        from code_muse.plugins.code_critic.reviewer import review_code

        result = _run_async(
            review_code(
                file_path="test.js",
                code_snippet="function foo() {",  # truncated
            )
        )
        assert isinstance(result, dict)
        assert result["verdict"] == "rejected"

    def test_empty_code_returns_rejected_dict(self) -> None:
        """Empty code should be caught by preflight."""
        from code_muse.plugins.code_critic.reviewer import review_code

        result = _run_async(
            review_code(
                file_path="test.py",
                code_snippet="",
            )
        )
        assert isinstance(result, dict)
        assert result["verdict"] == "rejected"

    def test_valid_python_returns_dict_shape(self) -> None:
        """For valid Python, review_code returns a dict with the expected
        shape (may call LLM or fail — shape is what matters)."""
        # Mock the LLM to avoid needing a real model
        from code_muse.plugins.code_critic import reviewer
        from code_muse.plugins.code_critic.reviewer import review_code

        with patch.object(
            reviewer,
            "_review_code_with_llm",
            new_callable=AsyncMock,
            return_value={
                "verdict": "approved",
                "summary": "looks good",
                "issues": [],
                "suggestion": None,
            },
        ):
            result = _run_async(
                review_code(
                    file_path="test.py",
                    code_snippet="x = 1\n",
                )
            )
            assert isinstance(result, dict)
            assert result["verdict"] == "approved"
            assert "summary" in result
            assert "issues" in result

    def test_detect_code_truncation_still_works(self) -> None:
        """The backward-compat _detect_code_truncation wrapper still works."""
        from code_muse.plugins.code_critic.reviewer import _detect_code_truncation

        is_trunc, reason = _detect_code_truncation("def foo(", "test.py")
        assert is_trunc is True
        assert reason is not None


# ===================================================================
# 6. Golden truncation set — deterministic false-negative gate
# ===================================================================


class TestGoldenTruncationSet:
    """Deterministic offline test demonstrating that the preflight gate
    catches truncated code with zero false negatives on this golden set.

    This is NOT a statistical claim about all possible inputs — it's a
    deterministic assertion on a representative set.  For broader
    coverage, see tests/plugins/truncation_detector/test_detector.py.
    """

    # (code, file_path, should_be_rejected)
    CASES: list[tuple[str, str, bool]] = [
        # --- Clearly truncated (should all be rejected) ---
        ("", "empty.py", True),
        ("   ", "whitespace.py", True),
        ("def foo(", "trunc1.py", True),
        ("class Bar", "trunc2.py", True),
        ("if x", "trunc3.py", True),
        ("function foo() {", "trunc4.js", True),
        ("const x", "trunc5.ts", True),
        ("{", "trunc6.rs", True),
        ("[", "trunc7.go", True),
        ("fn main() {", "trunc8.rs", True),
        ("impl Foo", "trunc9.rs", True),
        ("export default", "trunc10.ts", True),
        ("def hello():\n    return\nmonkeypatch.", "trunc11.py", True),
        # --- Clearly valid (should all pass) ---
        ("x = 1\n", "valid1.py", False),
        ("def hello():\n    return 'world'\n", "valid2.py", False),
        ("class Foo:\n    pass\n", "valid3.py", False),
        ("function foo() { return 1; }\n", "valid4.js", False),
        ('fn main() { println!("hi"); }\n', "valid5.rs", False),
        ("# Just a comment\n", "valid6.py", False),
        ('{"key": "value"}', "valid7.json", False),
    ]

    @pytest.mark.parametrize(
        "code,file_path,should_reject",
        CASES,
        ids=[f"{fp}-{'reject' if r else 'pass'}" for _, fp, r in CASES],
    )
    def test_golden_set(self, code: str, file_path: str, should_reject: bool) -> None:
        result = run_preflight(code, file_path)
        if should_reject:
            assert result is not None, (
                f"Expected {file_path!r} to be rejected, but preflight passed"
            )
            assert result.verdict == VerdictKind.REJECTED
            assert result.preflight_rejected is True
        else:
            assert result is None, (
                f"Expected {file_path!r} to pass preflight, but got rejected: "
                f"{result.summary}"
            )
