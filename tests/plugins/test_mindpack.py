"""Tests for MindPack expert agent factory and orchestration wiring.

These tests exercise the factory, prompt builder, and orchestrator
 WITHOUT actually calling an LLM — they validate the structural
integrity of the pipeline, not the model's output quality.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from code_muse.plugins.mindpack.factory import (
    READ_ONLY_TOOLS,
    ExpertAgentFactory,
    _MinimalAgentProxy,
    build_expert_prompt,
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
)
from code_muse.plugins.mindpack.schemas import MindPackExpertReport as ExpertReport

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def scout_descriptor() -> ExpertDescriptor:
    return ExpertDescriptor(
        name="Scout",
        speciality="codebase exploration & context gathering",
        system_prompt_fragment=(
            "You are Scout, the codebase explorer. Your job is to quickly "
            "scan relevant files, trace dependencies, and surface the "
            "context needed to understand a problem."
        ),
    )


@pytest.fixture
def sample_request() -> AskMindPackInput:
    return AskMindPackInput(
        problem_statement="Fix the auth bypass in login.py",
        current_goal="Ship the security patch",
        relevant_files=["auth/login.py", "tests/test_login.py"],
        observed_errors=["403 on valid credentials"],
        desired_output="debug_strategy",
    )


# ---------------------------------------------------------------------------
# ExpertDescriptor (schemas.py)
# ---------------------------------------------------------------------------


class TestExpertDescriptor:
    def test_defaults(self):
        e = ExpertDescriptor(name="A", speciality="B")
        assert e.system_prompt_fragment == ""
        assert e.max_experts_override is None

    def test_full_fields(self):
        e = ExpertDescriptor(
            name="A",
            speciality="B",
            system_prompt_fragment="Be wise",
            max_experts_override=3,
        )
        assert e.system_prompt_fragment == "Be wise"
        assert e.max_experts_override == 3


# ---------------------------------------------------------------------------
# READ_ONLY_TOOLS
# ---------------------------------------------------------------------------


class TestReadOnlyTools:
    def test_no_write_tools(self):
        write_tools = {
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
        overlap = set(READ_ONLY_TOOLS) & write_tools
        assert overlap == set(), f"Write tools leaked into READ_ONLY_TOOLS: {overlap}"

    def test_has_core_read_tools(self):
        assert "list_files" in READ_ONLY_TOOLS
        assert "read_file" in READ_ONLY_TOOLS
        assert "grep" in READ_ONLY_TOOLS


# ---------------------------------------------------------------------------
# build_expert_prompt
# ---------------------------------------------------------------------------


class TestBuildExpertPrompt:
    def test_includes_problem_statement(self, scout_descriptor, sample_request):
        prompt = build_expert_prompt(scout_descriptor, sample_request)
        assert "Fix the auth bypass" in prompt

    def test_includes_relevant_files(self, scout_descriptor, sample_request):
        prompt = build_expert_prompt(scout_descriptor, sample_request)
        assert "auth/login.py" in prompt
        assert "tests/test_login.py" in prompt

    def test_includes_errors(self, scout_descriptor, sample_request):
        prompt = build_expert_prompt(scout_descriptor, sample_request)
        assert "403 on valid credentials" in prompt

    def test_optional_fields_omitted(self, scout_descriptor):
        request = AskMindPackInput(
            problem_statement="Quick check",
            current_goal="Verify",
            desired_output="review",
        )
        prompt = build_expert_prompt(scout_descriptor, request)
        assert "Current Plan" not in prompt
        assert "What Has Been Tried" not in prompt
        assert "Relevant Files" not in prompt
        assert "Observed Errors" not in prompt
        assert "Uncertainty" not in prompt


# ---------------------------------------------------------------------------
# ExpertAgentFactory — structural tests (no LLM calls)
# ---------------------------------------------------------------------------


class TestExpertAgentFactory:
    @pytest.mark.asyncio
    async def test_resolve_model_name_raises_without_config(self):
        factory = ExpertAgentFactory()
        with patch(
            "code_muse.plugins.mindpack.factory.ExpertAgentFactory._resolve_model_name",
            side_effect=ValueError("No global model configured"),
        ):
            report = await factory.invoke_expert(
                ExpertDescriptor(name="X", speciality="Y"),
                AskMindPackInput(
                    problem_statement="test",
                    current_goal="test",
                ),
                "session-1",
            )
            assert report is None

    def test_fallback_report(self):
        report = ExpertAgentFactory._fallback_report(
            ExpertDescriptor(name="Scout", speciality="Exploration"),
            "sess-1",
            "connection timeout",
        )
        assert report.expert_id == "Scout"
        assert report.run_id == "sess-1"
        assert report.confidence == 0.0
        assert "connection timeout" in report.risks[0]

    def test_extract_report_structured(self):
        expert = ExpertDescriptor(name="Architect", speciality="Design")
        report = ExpertReport(
            expert_id="Architect",
            run_id="wrong-session",
            lens="design",
            prompt_variant="default",
            summary="Good analysis",
            findings=["Use interfaces"],
            proposed_plan=["Refactor module"],
            risks=["Over-engineering"],
            files_to_inspect=["app.py"],
            confidence=0.8,
            status="success",
        )
        result = MagicMock()
        result.output = report

        extracted = ExpertAgentFactory._extract_report(
            result, expert, "correct-session"
        )
        assert extracted is not None
        assert extracted.run_id == "correct-session"
        assert extracted.expert_id == "Architect"

    def test_extract_report_text_fallback(self):
        expert = ExpertDescriptor(name="Scout", speciality="Exploration")
        result = MagicMock()
        result.output = "Some plain text analysis"

        extracted = ExpertAgentFactory._extract_report(result, expert, "sess-1")
        assert extracted is not None
        assert "Some plain text analysis" in extracted.summary
        assert extracted.confidence == 0.3
        assert "Fallback" in extracted.risks[0]

    def test_extract_report_none(self):
        expert = ExpertDescriptor(name="A", speciality="B")
        extracted = ExpertAgentFactory._extract_report(None, expert, "sess-1")
        assert extracted is None


# ---------------------------------------------------------------------------
# _MinimalAgentProxy
# ---------------------------------------------------------------------------


class TestMinimalAgentProxy:
    def test_name(self):
        proxy = _MinimalAgentProxy("Watchdog")
        assert proxy.name == "mindpack-Watchdog"

    def test_get_model_name(self):
        proxy = _MinimalAgentProxy("Architect")
        with patch("code_muse.config.get_global_model_name", return_value="claude-3"):
            assert proxy.get_model_name() == "claude-3"


# ---------------------------------------------------------------------------
# MindPackOrchestrator wiring
# ---------------------------------------------------------------------------


class TestOrchestratorWiring:
    def setup_method(self):
        self._active_profile_patcher = patch.object(
            MindPackOrchestrator, "get_active_profile_name", return_value=None
        )
        self._active_profile_patcher.start()

    def teardown_method(self):
        self._active_profile_patcher.stop()

    def test_default_factory_injected(self):
        o = MindPackOrchestrator()
        assert isinstance(o._factory, ExpertAgentFactory)

    def test_custom_factory_injected(self):
        mock_factory = MagicMock(spec=ExpertAgentFactory)
        o = MindPackOrchestrator(expert_factory=mock_factory)
        assert o._factory is mock_factory

    def test_register_expert(self):
        o = MindPackOrchestrator()
        o.register_expert(ExpertDescriptor(name="X", speciality="Y"))
        assert len(o.expert_registry) == 1
        assert o.expert_registry[0].name == "X"

    def test_register_experts(self):
        o = MindPackOrchestrator()
        o.register_experts(
            [
                ExpertDescriptor(name="A", speciality="X"),
                ExpertDescriptor(name="B", speciality="Y"),
            ]
        )
        assert len(o.expert_registry) == 2

    def test_expert_registry_is_copy(self):
        o = MindPackOrchestrator()
        o.register_expert(ExpertDescriptor(name="A", speciality="B"))
        reg = o.expert_registry
        reg.clear()
        # Original should be unaffected
        assert len(o.expert_registry) == 1

    @pytest.mark.asyncio
    async def test_invoke_expert_delegates_to_factory(
        self, scout_descriptor, sample_request
    ):
        mock_factory = AsyncMock(spec=ExpertAgentFactory)
        expected_report = ExpertReport(
            expert_id="Scout",
            run_id="test-sess",
            lens="exploration",
            prompt_variant="default",
            summary="Look at auth.py",
            findings=["Check line 42"],
            proposed_plan=["Fix auth"],
            risks=["SQL injection possible"],
            files_to_inspect=["auth/login.py"],
            confidence=0.75,
            status="success",
        )
        mock_factory.invoke_expert.return_value = expected_report

        o = MindPackOrchestrator(expert_factory=mock_factory)
        report = await o._invoke_expert("test-sess", sample_request, scout_descriptor)

        mock_factory.invoke_expert.assert_awaited_once_with(
            scout_descriptor, sample_request, "test-sess"
        )
        assert report is expected_report
        assert report.expert_id == "Scout"
        assert report.confidence == 0.75

    @pytest.mark.asyncio
    async def test_invoke_expert_fallback_on_exception(
        self, scout_descriptor, sample_request
    ):
        mock_factory = AsyncMock(spec=ExpertAgentFactory)
        mock_factory.invoke_expert.side_effect = RuntimeError("model down")

        o = MindPackOrchestrator(expert_factory=mock_factory)
        report = await o._invoke_expert("test-sess", sample_request, scout_descriptor)

        assert report is not None
        assert report.confidence == 0.0
        assert "model down" in report.risks[0]

    @pytest.mark.asyncio
    async def test_spawn_and_collect_stores_reports(self, sample_request):
        expert1 = ExpertDescriptor(name="A", speciality="X")
        expert2 = ExpertDescriptor(name="B", speciality="Y")

        mock_factory = AsyncMock(spec=ExpertAgentFactory)

        report1 = ExpertReport(
            expert_id="A",
            run_id="s1",
            lens="test",
            prompt_variant="default",
            summary="A says hi",
            findings=[],
            proposed_plan=[],
            risks=[],
            files_to_inspect=[],
            confidence=0.5,
            status="success",
        )
        report2 = ExpertReport(
            expert_id="B",
            run_id="s1",
            lens="test",
            prompt_variant="default",
            summary="B says hi",
            findings=[],
            proposed_plan=[],
            risks=[],
            files_to_inspect=[],
            confidence=0.6,
            status="success",
        )
        mock_factory.invoke_expert.side_effect = [report1, report2]

        store = ReportStore()
        o = MindPackOrchestrator(
            report_store=store,
            expert_factory=mock_factory,
        )
        o.register_experts([expert1, expert2])

        reports = await o._spawn_and_collect("s1", sample_request, [expert1, expert2])
        assert len(reports) == 2
        assert store.report_count("s1") == 2

    @pytest.mark.asyncio
    async def test_spawn_and_collect_skips_none(self, sample_request):
        expert = ExpertDescriptor(name="A", speciality="X")
        mock_factory = AsyncMock(spec=ExpertAgentFactory)
        mock_factory.invoke_expert.return_value = None

        store = ReportStore()
        o = MindPackOrchestrator(
            report_store=store,
            expert_factory=mock_factory,
        )

        reports = await o._spawn_and_collect("s1", sample_request, [expert])
        assert len(reports) == 0
        assert store.report_count("s1") == 0


# ---------------------------------------------------------------------------
# PlaceholderJudgeMerger (still works with real reports)
# ---------------------------------------------------------------------------


class TestPlaceholderJudgeMerger:
    @pytest.mark.asyncio
    async def test_merge_with_reports(self, sample_request):
        merger = PlaceholderJudgeMerger()
        reports = [
            ExpertReport(
                expert_id="A",
                run_id="s1",
                lens="test",
                prompt_variant="default",
                summary="A",
                findings=["Do X"],
                proposed_plan=["Step 1"],
                risks=["Risk1"],
                files_to_inspect=["f1.py"],
                confidence=0.7,
                status="success",
            ),
            ExpertReport(
                expert_id="B",
                run_id="s1",
                lens="test",
                prompt_variant="default",
                summary="B",
                findings=["Do Y"],
                proposed_plan=["Step 2"],
                risks=["Risk2"],
                files_to_inspect=["f2.py"],
                confidence=0.8,
                status="success",
            ),
        ]
        output = await merger.merge(sample_request, reports, "s1")
        assert isinstance(output, AskMindPackOutput)
        assert output.confidence == pytest.approx(0.75)
        assert output.disagreements == []
        assert "Risk1" in output.risks
        assert "Step 1" in output.recommended_plan


# ---------------------------------------------------------------------------
# DefaultExpertSelector
# ---------------------------------------------------------------------------


class TestDefaultExpertSelector:
    def test_select_all(self, sample_request):
        selector = DefaultExpertSelector()
        experts = [ExpertDescriptor(name=str(i), speciality="X") for i in range(5)]
        selected = selector.select(sample_request, experts)
        assert len(selected) == 5

    def test_select_cap(self):
        selector = DefaultExpertSelector()
        request = AskMindPackInput(
            problem_statement="test",
            current_goal="test",
            max_experts=2,
        )
        experts = [ExpertDescriptor(name=str(i), speciality="X") for i in range(5)]
        selected = selector.select(request, experts)
        assert len(selected) == 2


# ---------------------------------------------------------------------------
# Expert persistence (save_experts / load_experts)
# ---------------------------------------------------------------------------


class TestExpertPersistence:
    def setup_method(self):
        self._active_profile_patcher = patch.object(
            MindPackOrchestrator, "get_active_profile_name", return_value=None
        )
        self._active_profile_patcher.start()

    def teardown_method(self):
        self._active_profile_patcher.stop()

    def test_save_experts_writes_json(self, tmp_path):
        o = MindPackOrchestrator()
        o.register_experts(
            [
                ExpertDescriptor(name="Scout", speciality="Exploration", model="fast"),
                ExpertDescriptor(name="Architect", speciality="Design"),
            ]
        )

        config_path = tmp_path / "experts.json"
        with patch.object(
            MindPackOrchestrator, "_get_experts_config_path", return_value=config_path
        ):
            o.save_experts()

        assert config_path.exists()
        data = json.loads(config_path.read_text(encoding="utf-8"))
        assert len(data) == 2
        assert data[0]["name"] == "Scout"
        assert data[0]["model"] == "fast"
        assert data[1]["name"] == "Architect"
        assert data[1]["model"] is None

    def test_load_experts_merges_with_defaults(self, tmp_path):
        config_path = tmp_path / "experts.json"
        custom_experts = [
            {
                "name": "SecurityReviewer",
                "speciality": "security",
                "system_prompt_fragment": "Be secure",
                "model": "strong",
                "max_experts_override": None,
            }
        ]
        config_path.write_text(json.dumps(custom_experts), encoding="utf-8")

        o = MindPackOrchestrator()
        o.register_expert(ExpertDescriptor(name="Scout", speciality="Exploration"))
        o.register_expert(
            ExpertDescriptor(name="SecurityReviewer", speciality="old spec")
        )

        with patch.object(
            MindPackOrchestrator, "_get_experts_config_path", return_value=config_path
        ):
            o.load_experts()

        names = [e.name for e in o.expert_registry]
        assert "Scout" in names  # preserved default
        assert "SecurityReviewer" in names  # replaced by config
        # The SecurityReviewer should have the config version's speciality
        sr = next(e for e in o.expert_registry if e.name == "SecurityReviewer")
        assert sr.speciality == "security"
        assert sr.model == "strong"

    def test_load_experts_no_config_file(self, tmp_path):
        config_path = tmp_path / "nonexistent.json"
        o = MindPackOrchestrator()
        o.register_expert(ExpertDescriptor(name="Scout", speciality="Exploration"))

        with patch.object(
            MindPackOrchestrator, "_get_experts_config_path", return_value=config_path
        ):
            o.load_experts()  # should not raise

        assert len(o.expert_registry) == 1

    def test_load_experts_handles_corrupt_file(self, tmp_path):
        config_path = tmp_path / "experts.json"
        config_path.write_text("not valid json{{{", encoding="utf-8")

        o = MindPackOrchestrator()
        o.register_expert(ExpertDescriptor(name="Scout", speciality="Exploration"))

        with patch.object(
            MindPackOrchestrator, "_get_experts_config_path", return_value=config_path
        ):
            o.load_experts()  # should not raise, logs error

        # Existing experts should remain untouched
        assert len(o.expert_registry) == 1
        assert o.expert_registry[0].name == "Scout"

    def test_save_then_load_roundtrip(self, tmp_path):
        config_path = tmp_path / "experts.json"

        # Save
        o1 = MindPackOrchestrator()
        o1.register_experts(
            [
                ExpertDescriptor(
                    name="Custom",
                    speciality="Custom spec",
                    system_prompt_fragment="Be custom",
                    model="medium",
                    max_experts_override=3,
                ),
            ]
        )
        with patch.object(
            MindPackOrchestrator, "_get_experts_config_path", return_value=config_path
        ):
            o1.save_experts()

        # Load into a fresh orchestrator with some defaults
        o2 = MindPackOrchestrator()
        o2.register_expert(ExpertDescriptor(name="Scout", speciality="Exploration"))
        with patch.object(
            MindPackOrchestrator, "_get_experts_config_path", return_value=config_path
        ):
            o2.load_experts()

        names = [e.name for e in o2.expert_registry]
        assert "Scout" in names
        assert "Custom" in names
        custom = next(e for e in o2.expert_registry if e.name == "Custom")
        assert custom.speciality == "Custom spec"
        assert custom.model == "medium"
        assert custom.max_experts_override == 3

    def test_get_experts_config_path_creates_dir(self, tmp_path):
        fake_home = tmp_path / "fake_home"
        with patch("pathlib.Path.home", return_value=fake_home):
            path = MindPackOrchestrator._get_experts_config_path()
            assert path.parent.exists()
            assert path.name == "experts.json"


# ---------------------------------------------------------------------------
# Preset expert templates
# ---------------------------------------------------------------------------


class TestPresetExperts:
    def test_preset_experts_importable(self):
        from code_muse.plugins.mindpack.mindpack_menu import PRESET_EXPERTS

        assert len(PRESET_EXPERTS) == 5

    def test_preset_expert_names(self):
        from code_muse.plugins.mindpack.mindpack_menu import PRESET_EXPERTS

        names = [e.name for e in PRESET_EXPERTS]
        assert "SecurityReviewer" in names
        assert "PerfReviewer" in names
        assert "UXReviewer" in names
        assert "APReviewer" in names
        assert "DBReviewer" in names

    def test_preset_experts_have_prompt_fragments(self):
        from code_muse.plugins.mindpack.mindpack_menu import PRESET_EXPERTS

        for expert in PRESET_EXPERTS:
            assert expert.system_prompt_fragment
            assert len(expert.system_prompt_fragment) > 20

    def test_preset_experts_have_models(self):
        from code_muse.plugins.mindpack.mindpack_menu import PRESET_EXPERTS

        for expert in PRESET_EXPERTS:
            assert expert.model in ("strong", "medium", None)
