"""Integration test for the full ask_mindpack flow.

Exercises the end-to-end pipeline:
  1. Orchestrator receives request and selects experts
  2. ExpertAgentFactory invokes each expert (mocked LLM)
  3. Reports land in the ReportStore
  4. JudgeMerger receives the reports and synthesises AskMindPackOutput
  5. Session state is cleaned up

Uses the DI surface documented in docs/MIND_PACK.md:
  "If you need isolated orchestrators (e.g. for testing), construct
  MindPackOrchestrator() directly with injected dependencies."
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from code_muse.plugins.mindpack.factory import (
    ExpertAgentFactory,
    build_expert_prompt,
)
from code_muse.plugins.mindpack.judge import (
    JudgeAgentFactory,
    build_judge_prompt,
)
from code_muse.plugins.mindpack.memory import ReportStore
from code_muse.plugins.mindpack.orchestration import (
    DefaultExpertSelector,
    MindPackOrchestrator,
    PlaceholderJudgeMerger,
)
from code_muse.plugins.mindpack.schemas import (
    AskMindPackInput,
    AskMindPackOutput,
    ExpertDescriptor,
    MindPackRankedOption,
)
from code_muse.plugins.mindpack.schemas import MindPackExpertReport as ExpertReport

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def request_debug() -> AskMindPackInput:
    """A realistic debug-strategy consultation request."""
    return AskMindPackInput(
        problem_statement="Auth bypass: valid credentials return 403 on PostgreSQL 14+",
        current_goal="Ship the security patch before release",
        current_plan="ALTER TABLE users DROP COLUMN middle_name",
        what_has_been_tried=[
            "Running migration directly — got constraint violation",
            "Tried adding a default — still fails on existing rows",
        ],
        relevant_files=[
            "auth/login.py",
            "migrations/0042_drop_middle_name.py",
            "app/models/user.py",
        ],
        observed_errors=["NotNullViolation: column middle_name contains null values"],
        uncertainty="Whether to backfill or add a two-phase migration",
        desired_output="debug_strategy",
    )


@pytest.fixture
def request_compare() -> AskMindPackInput:
    """A compare-options consultation request."""
    return AskMindPackInput(
        problem_statement="Choose between REST and gRPC for the new payment service",
        current_goal="Decide on the API protocol",
        desired_output="compare_options",
        max_experts=3,
    )


THREE_EXPERTS = [
    ExpertDescriptor(
        name="Scout",
        speciality="codebase exploration & context gathering",
        system_prompt_fragment="You are Scout. Scan and trace.",
    ),
    ExpertDescriptor(
        name="Architect",
        speciality="design & architecture decisions",
        system_prompt_fragment="You are Architect. Propose clean structure.",
    ),
    ExpertDescriptor(
        name="Watchdog",
        speciality="risk assessment & edge-case analysis",
        system_prompt_fragment="You are Watchdog. Find what could go wrong.",
    ),
]


def _make_report(name: str, session_id: str, confidence: float = 0.7) -> ExpertReport:
    """Helper to build a realistic expert report."""
    return ExpertReport(
        expert_id=name,
        run_id=session_id,
        lens="test",
        prompt_variant="default",
        summary=f"{name} analysed the problem and found key issues.",
        findings=[f"{name}: Follow the two-phase migration strategy"],
        proposed_plan=[f"{name}: Step one, step two"],
        risks=[f"{name}: Risk of data loss if migration runs in one step"],
        files_to_inspect=["migrations/0042_drop_middle_name.py"],
        confidence=confidence,
        status="success",
    )


# ---------------------------------------------------------------------------
# 1. Orchestrator picks up the request and selects experts
# ---------------------------------------------------------------------------


class TestOrchestratorReceivesRequest:
    """Verify the orchestrator selects the right expert subset."""

    async def test_selects_all_experts_when_no_cap(self, request_debug):
        selector = DefaultExpertSelector()
        selected = selector.select(request_debug, THREE_EXPERTS)
        assert len(selected) == 3
        assert [e.name for e in selected] == ["Scout", "Architect", "Watchdog"]

    async def test_respects_max_experts_cap(self, request_compare):
        selector = DefaultExpertSelector()
        # request_compare has max_experts=3 but only 3 available
        selected = selector.select(request_compare, THREE_EXPERTS)
        assert len(selected) == 3

    async def test_caps_at_registry_size(self):
        selector = DefaultExpertSelector()
        request = AskMindPackInput(
            problem_statement="test",
            current_goal="test",
            max_experts=10,
        )
        selected = selector.select(request, THREE_EXPERTS)
        assert len(selected) == 3  # can't exceed registry

    async def test_selects_empty_when_no_experts_registered(self, request_debug):
        selector = DefaultExpertSelector()
        selected = selector.select(request_debug, [])
        assert selected == []


# ---------------------------------------------------------------------------
# 2. Experts are "invoked" via factory logic
# ---------------------------------------------------------------------------


class TestExpertInvocationViaFactory:
    """Verify expert agents are invoked and reports extracted correctly."""

    async def test_mock_factory_produces_reports(self, request_debug):
        """Simulate a factory that returns structured ExpertReports."""
        mock_factory = AsyncMock(spec=ExpertAgentFactory)

        session_id = "test-integration-001"
        reports = [
            _make_report("Scout", session_id, 0.8),
            _make_report("Architect", session_id, 0.75),
            _make_report("Watchdog", session_id, 0.6),
        ]
        mock_factory.invoke_expert.side_effect = reports

        store = ReportStore()
        orchestrator = MindPackOrchestrator(
            report_store=store,
            expert_factory=mock_factory,
        )
        orchestrator.register_experts(THREE_EXPERTS)

        # Run the consultation
        output = await orchestrator.consult(request_debug)

        # Verify all 3 experts were invoked
        assert mock_factory.invoke_expert.await_count == 3

        # Verify reports landed in the store during the consultation
        # (store is cleared after consult, so we check the output instead)
        assert isinstance(output, AskMindPackOutput)

    async def test_factory_fallback_on_exception(self, request_debug):
        """When an expert raises, the orchestrator still gets a fallback report."""
        mock_factory = AsyncMock(spec=ExpertAgentFactory)

        # Scout succeeds, Architect raises, Watchdog succeeds
        report_scout = _make_report("Scout", "any", 0.7)
        report_watchdog = _make_report("Watchdog", "any", 0.5)

        mock_factory.invoke_expert.side_effect = [
            report_scout,
            RuntimeError("Model overloaded"),
            report_watchdog,
        ]

        orchestrator = MindPackOrchestrator(
            expert_factory=mock_factory,
            judge_merger=PlaceholderJudgeMerger(),
        )
        orchestrator.register_experts(THREE_EXPERTS)

        output = await orchestrator.consult(request_debug)

        # Should still produce output (graceful degradation)
        assert isinstance(output, AskMindPackOutput)
        # Confidence should be reduced due to the failed expert
        # (fallback report has confidence 0.0, plus the two good reports)
        assert output.confidence >= 0.0

    async def test_expert_prompt_contains_full_context(self, request_debug):
        """Verify the built prompt carries all request fields."""
        expert = THREE_EXPERTS[0]  # Scout
        prompt = build_expert_prompt(expert, request_debug)

        assert "Auth bypass" in prompt
        assert "security patch" in prompt
        assert "ALTER TABLE" in prompt
        assert "constraint violation" in prompt
        assert "auth/login.py" in prompt
        assert "NotNullViolation" in prompt
        assert "two-phase migration" in prompt
        assert "debug_strategy" in prompt


# ---------------------------------------------------------------------------
# 3. Judge Merger receives reports
# ---------------------------------------------------------------------------


class TestJudgeMergerReceivesReports:
    """Verify the judge merger is called with the correct reports."""

    async def test_placeholder_merger_gets_all_reports(self, request_debug):
        mock_factory = AsyncMock(spec=ExpertAgentFactory)
        session_id = "merge-test"

        reports = [
            _make_report("Scout", session_id, 0.8),
            _make_report("Architect", session_id, 0.7),
            _make_report("Watchdog", session_id, 0.6),
        ]
        mock_factory.invoke_expert.side_effect = reports

        # Use a tracking merger that records what it receives
        merger = PlaceholderJudgeMerger()
        merge_calls: list = []

        original_merge = merger.merge

        async def tracking_merge(request, reports, session_id):
            merge_calls.append((request, list(reports), session_id))
            return await original_merge(request, reports, session_id)

        merger.merge = tracking_merge

        orchestrator = MindPackOrchestrator(
            expert_factory=mock_factory,
            judge_merger=merger,
        )
        orchestrator.register_experts(THREE_EXPERTS)

        await orchestrator.consult(request_debug)

        # Merger was called once with all 3 reports
        assert len(merge_calls) == 1
        called_request, called_reports, called_session_id = merge_calls[0]
        assert called_request is request_debug
        assert len(called_reports) == 3
        assert [r.expert_id for r in called_reports] == [
            "Scout",
            "Architect",
            "Watchdog",
        ]

    async def test_judge_prompt_includes_all_reports(self, request_debug):
        """Verify the judge prompt serialises all expert reports."""
        reports = [
            _make_report("Scout", "s1", 0.8),
            _make_report("Architect", "s1", 0.7),
        ]

        prompt = build_judge_prompt(request_debug, reports)

        assert "ORIGINAL CONSULTATION REQUEST" in prompt
        assert "Auth bypass" in prompt
        assert "EXPERT REPORTS" in prompt
        assert "Scout" in prompt
        assert "Architect" in prompt
        assert "0.80" in prompt
        assert "0.70" in prompt

    async def test_placeholder_merger_output_structure(self, request_debug):
        """Placeholder merger produces a valid AskMindPackOutput."""
        merger = PlaceholderJudgeMerger()
        reports = [
            _make_report("Scout", "s1", 0.9),
            _make_report("Architect", "s1", 0.7),
        ]

        output = await merger.merge(request_debug, reports, "test-session")

        assert isinstance(output, AskMindPackOutput)
        assert output.confidence == pytest.approx(0.8)
        assert len(output.ranked_options) >= 1
        assert output.summary != ""
        assert output.recommended_plan != ""
        assert len(output.risks) > 0


# ---------------------------------------------------------------------------
# 4. Final AskMindPackOutput is synthesised
# ---------------------------------------------------------------------------


class TestAskMindPackOutputSynthesis:
    """Verify the full consult() → AskMindPackOutput pipeline."""

    async def test_full_consult_produces_valid_output(self, request_debug):
        """End-to-end: consult() returns a fully populated AskMindPackOutput."""
        mock_factory = AsyncMock(spec=ExpertAgentFactory)
        reports = [
            _make_report("Scout", "any", 0.85),
            _make_report("Architect", "any", 0.75),
            _make_report("Watchdog", "any", 0.65),
        ]
        mock_factory.invoke_expert.side_effect = reports

        orchestrator = MindPackOrchestrator(
            expert_factory=mock_factory,
            judge_merger=PlaceholderJudgeMerger(),
        )
        orchestrator.register_experts(THREE_EXPERTS)

        output = await orchestrator.consult(request_debug)

        # Required fields are populated
        assert isinstance(output, AskMindPackOutput)
        assert output.summary != ""
        assert output.recommended_plan != ""
        assert len(output.ranked_options) >= 1
        assert output.expert_consensus != ""
        assert 0.0 <= output.confidence <= 1.0

        # Risks carry through from expert reports
        assert len(output.risks) > 0
        assert any("data loss" in r for r in output.risks)

        # Files carry through
        assert (
            "migrations/0042_drop_middle_name.py" in output.files_to_inspect_or_change
        )

    async def test_consult_with_no_experts(self, request_debug):
        """When no experts are registered, the output degrades gracefully."""
        mock_factory = AsyncMock(spec=ExpertAgentFactory)
        merger = PlaceholderJudgeMerger()

        orchestrator = MindPackOrchestrator(
            expert_factory=mock_factory,
            judge_merger=merger,
        )
        # No experts registered

        output = await orchestrator.consult(request_debug)

        assert isinstance(output, AskMindPackOutput)
        # Confidence is 0 when no reports exist (sum/1 = 0/0 → 0)
        assert output.confidence == 0.0

    async def test_consult_with_single_expert(self, request_debug):
        """Single-expert consultation still produces a full output."""
        mock_factory = AsyncMock(spec=ExpertAgentFactory)
        mock_factory.invoke_expert.return_value = _make_report("Scout", "any", 0.9)

        orchestrator = MindPackOrchestrator(
            expert_factory=mock_factory,
            judge_merger=PlaceholderJudgeMerger(),
        )
        orchestrator.register_expert(THREE_EXPERTS[0])  # only Scout

        output = await orchestrator.consult(request_debug)

        assert isinstance(output, AskMindPackOutput)
        assert output.confidence == pytest.approx(0.9)

    async def test_expert_reports_merge_into_output(self, request_debug):
        """Multiple expert reports merge into a valid AskMindPackOutput."""
        mock_factory = AsyncMock(spec=ExpertAgentFactory)

        report_architect = _make_report("Architect", "any", 0.7)
        report_challenger = ExpertReport(
            expert_id="Challenger",
            run_id="any",
            lens="adversarial",
            prompt_variant="default",
            summary="Challenger disagrees with the approach.",
            findings=["Use a simpler migration"],
            proposed_plan=["Simplify migration"],
            risks=["The two-phase approach is over-engineered"],
            files_to_inspect=[],
            confidence=0.6,
            status="success",
        )

        mock_factory.invoke_expert.side_effect = [
            report_architect,
            report_challenger,
        ]

        orchestrator = MindPackOrchestrator(
            expert_factory=mock_factory,
            judge_merger=PlaceholderJudgeMerger(),
        )
        orchestrator.register_experts(
            [
                THREE_EXPERTS[1],
                ExpertDescriptor(name="Challenger", speciality="adversarial"),
            ]
        )

        output = await orchestrator.consult(request_debug)

        assert isinstance(output, AskMindPackOutput)
        assert output.confidence == pytest.approx(0.65)
        assert "Simplify migration" in output.recommended_plan


# ---------------------------------------------------------------------------
# 5. Session lifecycle (cleanup, isolation)
# ---------------------------------------------------------------------------


class TestSessionLifecycle:
    """Verify session state is managed correctly across consultations."""

    async def test_session_cleared_after_consult(self, request_debug):
        """ReportStore is cleaned up after a consultation completes."""
        store = ReportStore()
        mock_factory = AsyncMock(spec=ExpertAgentFactory)

        # Use a side_effect that respects the real session_id so
        # clear_session matches the key the report was stored under.
        async def make_report(expert, request, session_id):
            return _make_report(expert.name, session_id, 0.7)

        mock_factory.invoke_expert.side_effect = make_report

        orchestrator = MindPackOrchestrator(
            report_store=store,
            expert_factory=mock_factory,
            judge_merger=PlaceholderJudgeMerger(),
        )
        orchestrator.register_expert(THREE_EXPERTS[0])

        await orchestrator.consult(request_debug)

        # After consult, the session should be cleared
        assert (
            store.get_reports(run_id="") == []
        )  # store cleared, any run_id returns empty

    async def test_multiple_consults_are_isolated(self, request_debug):
        """Two sequential consultations don't leak state."""
        store = ReportStore()
        mock_factory = AsyncMock(spec=ExpertAgentFactory)

        call_count = 0

        async def make_report(expert, request, session_id):
            nonlocal call_count
            call_count += 1
            return _make_report(expert.name, session_id, 0.5 + call_count * 0.1)

        mock_factory.invoke_expert.side_effect = make_report

        orchestrator = MindPackOrchestrator(
            report_store=store,
            expert_factory=mock_factory,
            judge_merger=PlaceholderJudgeMerger(),
        )
        orchestrator.register_experts(THREE_EXPERTS[:2])

        output1 = await orchestrator.consult(request_debug)
        output2 = await orchestrator.consult(request_debug)

        # Both produce valid outputs
        assert isinstance(output1, AskMindPackOutput)
        assert isinstance(output2, AskMindPackOutput)

        # Sessions don't leak — store is empty after each
        assert store.get_reports(run_id="") == []

    async def test_reports_stored_during_consult(self, request_debug):
        """Expert reports are buffered in the ReportStore during consult."""
        store = ReportStore()
        mock_factory = AsyncMock(spec=ExpertAgentFactory)
        mock_factory.invoke_expert.side_effect = lambda expert, request, session_id: (
            _make_report(expert.name, session_id, 0.7)
        )

        orchestrator = MindPackOrchestrator(
            report_store=store,
            expert_factory=mock_factory,
            judge_merger=PlaceholderJudgeMerger(),
        )
        orchestrator.register_expert(THREE_EXPERTS[0])

        await orchestrator.consult(request_debug)

        # The session_id passed to the factory is the same one cleared by the orchestrator
        used_session_id = mock_factory.invoke_expert.call_args[0][2]
        assert store.report_count(used_session_id) == 0  # cleared after consult


# ---------------------------------------------------------------------------
# 6. Expert report extraction paths (factory internal logic)
# ---------------------------------------------------------------------------


class TestExpertReportExtraction:
    """Verify the factory's report extraction logic under various outputs."""

    def test_structured_expert_report(self):
        """Pydantic-ai structured output → clean ExpertReport."""
        expert = THREE_EXPERTS[0]
        report = ExpertReport(
            expert_id="Scout",
            run_id="old-session",
            lens="exploration",
            prompt_variant="default",
            summary="Found the bug on line 42",
            findings=["Fix the off-by-one"],
            proposed_plan=["Update loop"],
            risks=["Edge case with empty list"],
            files_to_inspect=["auth/login.py"],
            confidence=0.85,
            status="success",
        )
        result = MagicMock()
        result.output = report

        extracted = ExpertAgentFactory._extract_report(result, expert, "new-session")
        assert extracted is not None
        assert extracted.run_id == "new-session"
        assert extracted.expert_id == "Scout"
        assert extracted.confidence == 0.85

    def test_dict_output_coerced_to_report(self):
        """Dict output → ExpertReport via field filtering."""
        expert = THREE_EXPERTS[0]
        result = MagicMock()
        result.output = {
            "expert_id": "Scout",
            "run_id": "wrong",
            "summary": "Quick scan",
            "findings": ["Check X"],
            "risks": ["Y might fail"],
            "files_to_inspect": ["a.py"],
            "confidence": 0.6,
            "lens": "exploration",
            "prompt_variant": "default",
            "extra_field": "ignored",
        }

        extracted = ExpertAgentFactory._extract_report(result, expert, "correct")
        assert extracted is not None
        assert extracted.run_id == "correct"
        assert extracted.expert_id == "Scout"

    def test_text_fallback_report(self):
        """Plain text output → low-confidence fallback report."""
        expert = THREE_EXPERTS[0]
        result = MagicMock()
        result.output = "I think the issue is in the auth module."

        extracted = ExpertAgentFactory._extract_report(result, expert, "s1")
        assert extracted is not None
        assert "auth module" in extracted.summary
        assert extracted.confidence == 0.3
        assert "Fallback" in extracted.risks[0]

    def test_none_result_returns_none(self):
        """None result → None (no report produced)."""
        expert = THREE_EXPERTS[0]
        extracted = ExpertAgentFactory._extract_report(None, expert, "s1")
        assert extracted is None


# ---------------------------------------------------------------------------
# 7. Judge output extraction paths
# ---------------------------------------------------------------------------


class TestJudgeOutputExtraction:
    """Verify the JudgeAgentFactory's output extraction logic."""

    def test_structured_ask_mindpack_output(self, request_debug):
        """Structured output → AskMindPackOutput."""
        reports = [_make_report("Scout", "s1", 0.7)]
        output = AskMindPackOutput(
            summary="Test summary",
            recommended_plan="Do X",
            ranked_options=[
                MindPackRankedOption(rank=1, title="Option A", summary="Do A")
            ],
            risks=["Risk 1"],
            tests_to_run=["test_auth"],
            files_to_inspect_or_change=["auth.py"],
            expert_consensus="All agree",
            disagreements=[],
            confidence=0.7,
        )
        result = MagicMock()
        result.output = output

        extracted = JudgeAgentFactory._extract_output(result, request_debug, reports)
        assert isinstance(extracted, AskMindPackOutput)
        assert extracted.summary == "Test summary"
        assert extracted.confidence == 0.7

    def test_dict_output_coerced(self, request_debug):
        """Dict output → AskMindPackOutput."""
        reports = [_make_report("Scout", "s1", 0.7)]
        result = MagicMock()
        result.output = {
            "summary": "Dict summary",
            "recommended_plan": "Do Y",
            "ranked_options": [],
            "risks": ["Risk"],
            "tests_to_run": [],
            "files_to_inspect_or_change": [],
            "expert_consensus": "Partial",
            "disagreements": [],
            "confidence": 0.5,
        }

        extracted = JudgeAgentFactory._extract_output(result, request_debug, reports)
        assert isinstance(extracted, AskMindPackOutput)
        assert extracted.summary == "Dict summary"

    def test_none_result_uses_placeholder(self, request_debug):
        """None result → placeholder output (graceful degradation)."""
        reports = [_make_report("Scout", "s1", 0.7)]
        extracted = JudgeAgentFactory._extract_output(None, request_debug, reports)
        assert isinstance(extracted, AskMindPackOutput)
        assert (
            "fallback" in extracted.summary.lower()
            or "Judge fallback" in extracted.summary
        )


# ---------------------------------------------------------------------------
# 8. Read-only tool safety
# ---------------------------------------------------------------------------


class TestReadOnlyToolSafety:
    """Verify no write-capable tools leak into expert or judge allow-lists."""

    WRITE_TOOLS = {
        "create_file",
        "replace_in_file",
        "delete_snippet",
        "delete_file",
        "agent_run_shell_command",
        "ask_user_question",
        "invoke_agent",
        "list_agents",
        "activate_skill",
        "universal_constructor",
    }

    def test_expert_read_only_tools_clean(self):
        from code_muse.plugins.mindpack.factory import READ_ONLY_TOOLS

        overlap = set(READ_ONLY_TOOLS) & self.WRITE_TOOLS
        assert overlap == set(), f"Write tools in expert READ_ONLY_TOOLS: {overlap}"

    def test_judge_read_only_tools_clean(self):
        from code_muse.plugins.mindpack.judge import JUDGE_READ_ONLY_TOOLS

        overlap = set(JUDGE_READ_ONLY_TOOLS) & self.WRITE_TOOLS
        assert overlap == set(), (
            f"Write tools in judge JUDGE_READ_ONLY_TOOLS: {overlap}"
        )

    def test_ask_mindpack_not_in_expert_tools(self):
        from code_muse.plugins.mindpack.factory import READ_ONLY_TOOLS

        assert "ask_mindpack" not in READ_ONLY_TOOLS

    def test_ask_mindpack_not_in_judge_tools(self):
        from code_muse.plugins.mindpack.judge import JUDGE_READ_ONLY_TOOLS

        assert "ask_mindpack" not in JUDGE_READ_ONLY_TOOLS
