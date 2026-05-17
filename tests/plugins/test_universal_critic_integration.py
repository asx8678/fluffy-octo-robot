"""Tests for Universal Critic integration (orchestrator + callbacks)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic_ai.messages import ModelResponse, ToolCallPart

from code_muse.plugins.universal_critic.models import (
    AgentOutput,
    ReviewResult,
    TaskMetadata,
)
from code_muse.plugins.universal_critic.orchestrator import (
    MAX_REVIEW_ITERATIONS,
    _build_escalation_prompt,
    _build_rewrite_prompt,
    _extract_changed_files,
    _extract_file_path_from_tool_call,
    get_display_name,
)

# ---------------------------------------------------------------------------
# get_display_name
# ---------------------------------------------------------------------------


class TestGetDisplayName:
    """Tests for get_display_name."""

    def test_heavy_coding_agent(self):
        assert get_display_name("heavy-coding-agent") == "heavy coding agent"

    def test_light_coding_agent(self):
        assert get_display_name("light-coding-agent") == "light coding agent"

    def test_code_critic(self):
        assert get_display_name("code-critic") == "Universal Code Critic"

    def test_muse_title_cased(self):
        assert get_display_name("muse") == "Muse"

    def test_unknown_agent_title_cased(self):
        assert get_display_name("unknown-agent") == "Unknown Agent"


# ---------------------------------------------------------------------------
# _extract_changed_files
# ---------------------------------------------------------------------------


class TestExtractChangedFiles:
    """Tests for _extract_changed_files."""

    def test_no_all_messages(self):
        """Objects without all_messages() return empty list."""
        result = MagicMock(spec=[])  # no all_messages attribute
        assert _extract_changed_files(result) == []

    def test_extract_replace_in_file(self):
        """Extract file path from a replace_in_file tool call."""
        part = ToolCallPart(
            tool_name="replace_in_file",
            args={"file_path": "src/main.py", "replacements": []},
        )
        msg = ModelResponse(parts=[part])
        result = MagicMock()
        result.all_messages.return_value = [msg]
        assert _extract_changed_files(result) == ["src/main.py"]

    def test_extract_create_file(self):
        """Extract file path from a create_file tool call."""
        part = ToolCallPart(
            tool_name="create_file",
            args={"file_path": "new_module.py", "content": "pass"},
        )
        msg = ModelResponse(parts=[part])
        result = MagicMock()
        result.all_messages.return_value = [msg]
        assert _extract_changed_files(result) == ["new_module.py"]

    def test_deduplicate_paths(self):
        """Same file path from multiple tool calls is deduplicated."""
        part1 = ToolCallPart(
            tool_name="create_file",
            args={"file_path": "foo.py", "content": "v1"},
        )
        part2 = ToolCallPart(
            tool_name="replace_in_file",
            args={"file_path": "foo.py", "replacements": []},
        )
        msg = ModelResponse(parts=[part1, part2])
        result = MagicMock()
        result.all_messages.return_value = [msg]
        assert _extract_changed_files(result) == ["foo.py"]

    def test_ignore_non_file_tools(self):
        """Tool calls for non-file tools are ignored."""
        part = ToolCallPart(
            tool_name="agent_run_shell_command",
            args={"command": "ls"},
        )
        msg = ModelResponse(parts=[part])
        result = MagicMock()
        result.all_messages.return_value = [msg]
        assert _extract_changed_files(result) == []

    def test_multiple_files(self):
        """Multiple different files are all extracted."""
        parts = [
            ToolCallPart(
                tool_name="create_file",
                args={"file_path": "a.py", "content": "a"},
            ),
            ToolCallPart(
                tool_name="create_file",
                args={"file_path": "b.py", "content": "b"},
            ),
        ]
        msg = ModelResponse(parts=parts)
        result = MagicMock()
        result.all_messages.return_value = [msg]
        assert _extract_changed_files(result) == ["a.py", "b.py"]


# ---------------------------------------------------------------------------
# _extract_file_path_from_tool_call
# ---------------------------------------------------------------------------


class TestExtractFilePathFromToolCall:
    """Tests for _extract_file_path_from_tool_call."""

    def test_dict_args_file_path(self):
        part = ToolCallPart(
            tool_name="replace_in_file",
            args={"file_path": "src/main.py"},
        )
        assert _extract_file_path_from_tool_call(part) == "src/main.py"

    def test_dict_args_path(self):
        part = ToolCallPart(
            tool_name="create_file",
            args={"path": "other.py"},
        )
        assert _extract_file_path_from_tool_call(part) == "other.py"

    def test_json_string_args(self):
        part = ToolCallPart(
            tool_name="replace_in_file",
            args='{"file_path": "from_json.py"}',
        )
        assert _extract_file_path_from_tool_call(part) == "from_json.py"

    def test_no_file_path_key(self):
        part = ToolCallPart(
            tool_name="agent_run_shell_command",
            args={"command": "ls"},
        )
        assert _extract_file_path_from_tool_call(part) is None


# ---------------------------------------------------------------------------
# _build_rewrite_prompt / _build_escalation_prompt
# ---------------------------------------------------------------------------


class TestBuildRewritePrompt:
    """Tests for _build_rewrite_prompt."""

    def test_basic_rejection(self):
        result = ReviewResult(
            verdict="rejected",
            summary="Missing error handling",
            issues=["no try/except", "bare except"],
            suggestion="Add specific exception handling",
        )
        prompt = _build_rewrite_prompt(result, "utils.py", 1)
        assert "utils.py" in prompt
        assert "Missing error handling" in prompt
        assert "no try/except" in prompt
        assert "Add specific exception handling" in prompt

    def test_no_suggestion(self):
        result = ReviewResult(
            verdict="rejected",
            summary="Bad code",
            issues=["ugly"],
        )
        prompt = _build_rewrite_prompt(result, "bad.py", 1)
        assert "bad.py" in prompt
        assert "Suggestion" not in prompt


class TestBuildEscalationPrompt:
    """Tests for _build_escalation_prompt."""

    def test_escalation_content(self):
        result = ReviewResult(
            verdict="rejected",
            summary="Still bad",
            issues=["wrong approach"],
        )
        prompt = _build_escalation_prompt(result, "stuck.py", 9)
        assert "CRITICAL" in prompt
        assert "stuck.py" in prompt
        assert "9 times" in prompt
        assert "rethink" in prompt.lower()


# ---------------------------------------------------------------------------
# MAX_REVIEW_ITERATIONS
# ---------------------------------------------------------------------------


class TestMaxReviewIterations:
    """Tests for MAX_REVIEW_ITERATIONS constant."""

    def test_value_is_ten(self):
        assert MAX_REVIEW_ITERATIONS == 10


# ---------------------------------------------------------------------------
# Truncation detection (new fast-path guards)
# These tests are deliberately self-contained (no cross-test imports).
# ---------------------------------------------------------------------------

from code_muse.plugins.code_critic.reviewer import _detect_code_truncation  # noqa: E402


class TestDetectCodeTruncation:
    """Self-contained tests for the fast truncation / syntax guards."""

    def test_python_truncated_via_ast(self):
        bad_py = "def foo():\n    x = 1\n    monkeypatch."
        is_bad, reason = _detect_code_truncation(bad_py, "test_foo.py")
        assert is_bad is True
        assert (
            "syntax" in (reason or "").lower() or "truncated" in (reason or "").lower()
        )

    def test_python_valid_passes(self):
        good_py = "def add(a, b):\n    return a + b\n\nprint(add(1, 2))"
        is_bad, _ = _detect_code_truncation(good_py, "good.py")
        assert is_bad is False

    def test_js_truncated_ending(self):
        bad_js = "const handler = (req, res) => {\n    res.json({ ok: true"
        is_bad, reason = _detect_code_truncation(bad_js, "api.ts")
        assert is_bad is True
        assert (
            "incomplete token" in (reason or "").lower()
            or "bracket" in (reason or "").lower()
            or "partial identifier" in (reason or "").lower()
        )

    def test_go_truncated_declaration(self):
        bad_go = (
            "func handleRequest(w http.ResponseWriter, r *http.Request) {\n"
            "    fmt.Println("
        )
        is_bad, reason = _detect_code_truncation(bad_go, "server.go")
        assert is_bad is True

    def test_complete_rust_passes(self):
        good_rs = 'fn main() {\n    println!("hello");\n}'
        is_bad, _ = _detect_code_truncation(good_rs, "main.rs")
        assert is_bad is False

    def test_empty_file_detected(self):
        is_bad, _ = _detect_code_truncation("", "empty.py")
        assert is_bad is True


# ---------------------------------------------------------------------------
# review_on_result — integration-level tests
# ---------------------------------------------------------------------------


class TestReviewOnResult:
    """Tests for the review_on_result hook handler."""

    @pytest.mark.asyncio
    async def test_skip_code_critic_agent(self):
        """The critic's own runs should not be reviewed."""
        from code_muse.plugins.universal_critic.orchestrator import (
            review_on_result,
        )

        result = await review_on_result(MagicMock(), "code-critic", "model-x")
        assert result is None

    @pytest.mark.asyncio
    async def test_no_changed_files_returns_none(self):
        """If no file-writing tool calls, return None (no review)."""
        from code_muse.plugins.universal_critic.orchestrator import (
            _ITERATION_TRACKER,
            review_on_result,
        )

        # Clean tracker state
        _ITERATION_TRACKER.pop("test-agent", None)

        result_obj = MagicMock()
        result_obj.all_messages.return_value = []
        result = await review_on_result(result_obj, "test-agent", "model-x")
        assert result is None

    @pytest.mark.asyncio
    async def test_rejection_returns_retry_dict(self):
        """On rejection, returns a retry dict with source=critic."""
        from code_muse.plugins.universal_critic.orchestrator import (
            _ITERATION_TRACKER,
            review_on_result,
        )

        # Clean tracker state
        _ITERATION_TRACKER.pop("test-agent", None)

        # Build a mock result with a file-writing tool call
        part = ToolCallPart(
            tool_name="create_file",
            args={"file_path": "/tmp/test_review.py", "content": "bad code"},
        )
        msg = ModelResponse(parts=[part])
        result_obj = MagicMock()
        result_obj.all_messages.return_value = [msg]

        # Patch: file exists on disk, review returns rejected
        mock_review = ReviewResult(
            verdict="rejected",
            summary="Bad code",
            issues=["no tests"],
            suggestion="Add tests",
        )

        with (
            patch(
                "code_muse.plugins.universal_critic.orchestrator._read_file_content",
                return_value="bad code",
            ),
            patch(
                "code_muse.plugins.universal_critic.orchestrator.run_review",
                new_callable=AsyncMock,
                return_value=mock_review,
            ),
        ):
            result = await review_on_result(result_obj, "test-agent", "model-x")

        assert result is not None
        assert result["retry"] is True
        assert result["source"] == "critic"
        assert "prompt" in result
        assert result["delay"] == 0.5

        # Cleanup
        _ITERATION_TRACKER.pop("test-agent", None)

    @pytest.mark.asyncio
    async def test_approval_returns_none(self):
        """On approval, returns None (no retry needed)."""
        from code_muse.plugins.universal_critic.orchestrator import (
            _ITERATION_TRACKER,
            review_on_result,
        )

        _ITERATION_TRACKER.pop("test-agent", None)

        part = ToolCallPart(
            tool_name="create_file",
            args={"file_path": "/tmp/good_code.py", "content": "good"},
        )
        msg = ModelResponse(parts=[part])
        result_obj = MagicMock()
        result_obj.all_messages.return_value = [msg]

        mock_review = ReviewResult(
            verdict="approved",
            summary="LGTM",
        )

        with (
            patch(
                "code_muse.plugins.universal_critic.orchestrator._read_file_content",
                return_value="x = 1\n",
            ),
            patch(
                "code_muse.plugins.universal_critic.orchestrator._run_preflight",
                return_value=None,
            ),
            patch(
                "code_muse.plugins.universal_critic.orchestrator.run_review",
                new_callable=AsyncMock,
                return_value=mock_review,
            ),
        ):
            result = await review_on_result(result_obj, "test-agent", "model-x")

        assert result is None
        assert "test-agent" not in _ITERATION_TRACKER


# ---------------------------------------------------------------------------
# TaskMetadata dataclass
# ---------------------------------------------------------------------------


class TestTaskMetadata:
    """Tests for TaskMetadata dataclass."""

    def test_defaults(self):
        meta = TaskMetadata(original_prompt="test")
        assert meta.original_prompt == "test"
        assert meta.estimated_lines == 0
        assert meta.estimated_complexity == "unknown"
        assert meta.has_new_file_creation is False
        assert meta.has_shell_commands is False
        assert meta.has_multi_file_changes is False
        assert meta.routing_decision is None
        assert meta.originating_agent == "unknown"
        assert meta.iteration_count == 0

    def test_explicit_params(self):
        meta = TaskMetadata(
            original_prompt="implement auth",
            estimated_lines=40,
            estimated_complexity="complex",
            has_new_file_creation=True,
            has_shell_commands=True,
            has_multi_file_changes=False,
            routing_decision="heavy-coding-agent",
            originating_agent="muse",
            iteration_count=2,
        )
        assert meta.estimated_lines == 40
        assert meta.estimated_complexity == "complex"
        assert meta.has_new_file_creation is True
        assert meta.routing_decision == "heavy-coding-agent"
        assert meta.iteration_count == 2


# ---------------------------------------------------------------------------
# ReviewResult dataclass
# ---------------------------------------------------------------------------


class TestReviewResult:
    """Tests for ReviewResult dataclass."""

    def test_approved(self):
        result = ReviewResult(verdict="approved", summary="LGTM")
        assert result.verdict == "approved"
        assert result.summary == "LGTM"
        assert result.issues == []
        assert result.suggestion is None

    def test_rejected_with_issues(self):
        result = ReviewResult(
            verdict="rejected",
            summary="Bad code",
            issues=["missing tests", "no error handling"],
            suggestion="Add tests and try/except",
        )
        assert result.verdict == "rejected"
        assert len(result.issues) == 2
        assert result.suggestion == "Add tests and try/except"


# ---------------------------------------------------------------------------
# AgentOutput dataclass
# ---------------------------------------------------------------------------


class TestAgentOutput:
    """Tests for AgentOutput dataclass."""

    def test_heavy_coding_agent(self):
        output = AgentOutput(
            agent_name="heavy coding agent",
            originating_agent="heavy-coding-agent",
        )
        assert output.agent_name == "heavy coding agent"
        assert output.originating_agent == "heavy-coding-agent"
        assert output.file_paths == []
        assert output.code_snippets == {}
        assert output.summary == ""
        assert output.metadata == {}

    def test_light_coding_agent(self):
        output = AgentOutput(
            agent_name="light coding agent",
            originating_agent="light-coding-agent",
            file_paths=["utils.py"],
            summary="Fixed typo",
        )
        assert output.originating_agent == "light-coding-agent"
        assert output.file_paths == ["utils.py"]
