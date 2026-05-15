"""Tests for Universal Critic integration (orchestrator + callbacks)."""

from code_muse.plugins.universal_critic.models import (
    AgentOutput,
    ReviewResult,
    TaskMetadata,
)
from code_muse.plugins.universal_critic.orchestrator import (
    MAX_REVIEW_ITERATIONS,
    _extract_file_paths,
    _parse_response_for_review,
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
# _extract_file_paths
# ---------------------------------------------------------------------------


class TestExtractFilePaths:
    """Tests for _extract_file_paths."""

    def test_src_main_py(self):
        result = _extract_file_paths("Updated src/main.py with new logic")
        assert "src/main.py" in result

    def test_nested_plugin_path(self):
        result = _extract_file_paths("Edited code_muse/plugins/foo.py")
        assert "code_muse/plugins/foo.py" in result

    def test_readme_md(self):
        result = _extract_file_paths("See README.md for details")
        assert "README.md" in result

    def test_js_path(self):
        result = _extract_file_paths("Modified foo/bar/baz.js")
        assert "foo/bar/baz.js" in result

    def test_no_file_paths(self):
        result = _extract_file_paths("This has no file paths at all")
        assert result == []


# ---------------------------------------------------------------------------
# _parse_response_for_review
# ---------------------------------------------------------------------------


class TestParseResponseForReview:
    """Tests for _parse_response_for_review."""

    def test_code_block_with_file_annotation(self):
        text = "```python file.py\nprint('hello')\n```"
        items = _parse_response_for_review(text)
        assert len(items) == 1
        assert items[0]["file_path"] == "file.py"
        assert "print('hello')" in items[0]["code_snippet"]

    def test_no_code_blocks_falls_back_to_paths(self):
        text = "Updated utils.py and main.py"
        items = _parse_response_for_review(text)
        assert len(items) >= 1

    def test_empty_text(self):
        items = _parse_response_for_review("")
        assert items == []

    def test_malformed_code_block(self):
        text = "```python\n"
        items = _parse_response_for_review(text)
        # Should not crash — may return empty or partial
        assert isinstance(items, list)

    def test_multiple_code_blocks(self):
        text = "```python a.py\nx=1\n```\n```python b.py\ny=2\n```"
        items = _parse_response_for_review(text)
        assert len(items) == 2
        paths = [i["file_path"] for i in items]
        assert "a.py" in paths
        assert "b.py" in paths


# ---------------------------------------------------------------------------
# MAX_REVIEW_ITERATIONS
# ---------------------------------------------------------------------------


class TestMaxReviewIterations:
    """Tests for MAX_REVIEW_ITERATIONS constant."""

    def test_value_is_three(self):
        assert MAX_REVIEW_ITERATIONS == 3


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
