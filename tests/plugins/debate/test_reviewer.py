"""Tests for reviewer.py — JSON parsing, verdict construction, prompt building."""

from code_muse.plugins.debate.reviewer import (
    _build_user_prompt,
    _json_to_verdict,
    _load_reviewer_system_prompt,
    _parse_json_response,
)
from code_muse.plugins.debate.schemas import ReviewRequest, VerdictKind

# ---------------------------------------------------------------------------
# JSON parsing
# ---------------------------------------------------------------------------


class TestParseJsonResponse:
    def test_pure_json(self):
        text = '{"kind": "approve", "summary": "OK", "issues": [], "confidence": 0.9}'
        result = _parse_json_response(text)
        assert result is not None
        assert result["kind"] == "approve"

    def test_fenced_json_block(self):
        text = (
            "Review:\n"
            "```json\n"
            '{"kind": "revise", "summary": "Fix X", '
            '"issues": [], "confidence": 0.6}\n'
            "```"
        )
        result = _parse_json_response(text)
        assert result is not None
        assert result["kind"] == "revise"

    def test_embedded_braces(self):
        text = (
            'I think {"kind": "reject", "summary": "Bad", '
            '"issues": [], "confidence": 0.2} is my verdict'
        )
        result = _parse_json_response(text)
        assert result is not None
        assert result["kind"] == "reject"

    def test_unparseable_returns_none(self):
        assert _parse_json_response("I cannot review this.") is None

    def test_empty_string_returns_none(self):
        assert _parse_json_response("") is None

    def test_invalid_json_in_braces_returns_none(self):
        assert _parse_json_response("{not valid json}") is None


# ---------------------------------------------------------------------------
# Verdict construction
# ---------------------------------------------------------------------------


class TestJsonToVerdict:
    def test_valid_approve(self):
        v = _json_to_verdict(
            {"kind": "approve", "summary": "OK", "issues": [], "confidence": 0.95}
        )
        assert v.kind == VerdictKind.APPROVE
        assert v.confidence == 0.95
        assert len(v.issues) == 0

    def test_valid_revise_with_issues(self):
        v = _json_to_verdict(
            {
                "kind": "revise",
                "summary": "Fix bugs",
                "issues": [
                    {
                        "severity": "critical",
                        "message": "Null pointer",
                        "suggestion": "Add null check",
                    }
                ],
                "confidence": 0.7,
            }
        )
        assert v.kind == VerdictKind.REVISE
        assert len(v.issues) == 1
        assert v.issues[0].severity == "critical"
        assert v.issues[0].suggestion == "Add null check"

    def test_unknown_kind_falls_back_to_revise(self):
        v = _json_to_verdict({"kind": "maybe", "summary": "eh", "confidence": 1.5})
        assert v.kind == VerdictKind.REVISE
        assert v.confidence == 1.0  # clamped

    def test_negative_confidence_clamped(self):
        v = _json_to_verdict({"kind": "approve", "summary": "ok", "confidence": -0.5})
        assert v.confidence == 0.0

    def test_string_issue_shorthand(self):
        v = _json_to_verdict(
            {
                "kind": "revise",
                "summary": "fix",
                "issues": ["bad code"],
                "confidence": 0.3,
            }
        )
        assert len(v.issues) == 1
        assert v.issues[0].message == "bad code"

    def test_missing_keys_use_defaults(self):
        v = _json_to_verdict({})
        assert v.kind == VerdictKind.REVISE  # default "revise"
        assert v.summary == "No summary provided"
        assert v.confidence == 0.5

    def test_summary_truncated_at_500(self):
        v = _json_to_verdict(
            {
                "kind": "approve",
                "summary": "x" * 600,
                "confidence": 0.5,
            }
        )
        assert len(v.summary) == 500


# ---------------------------------------------------------------------------
# Prompt building
# ---------------------------------------------------------------------------


class TestPromptBuilding:
    def test_user_prompt_includes_proposal(self):
        req = ReviewRequest(
            proposal="Implement cache", reasoning_summary="For perf", checkpoint=2
        )
        prompt = _build_user_prompt(req)
        assert "Checkpoint 2" in prompt
        assert "Implement cache" in prompt
        assert "For perf" in prompt

    def test_user_prompt_without_reasoning(self):
        req = ReviewRequest(proposal="Do X", checkpoint=1)
        prompt = _build_user_prompt(req)
        assert "Checkpoint 1" in prompt
        assert "Do X" in prompt
        # Reasoning section should not appear when empty
        assert "Reasoning Summary" not in prompt

    def test_reviewer_system_prompt_loads(self):
        prompt = _load_reviewer_system_prompt()
        assert "approve" in prompt
        assert "revise" in prompt
        assert "reject" in prompt
        assert "reviewer" in prompt.lower()
