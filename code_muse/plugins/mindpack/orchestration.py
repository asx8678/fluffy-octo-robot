"""MindPack orchestration — MindPackOrchestrator lifecycle manager.

Orchestrates the full consultation lifecycle:
  1. Receive a consultation request (AskMindPackInput).
  2. Select and spawn expert agents via ExpertAgentFactory.
  3. Collect their reports into the ReportStore.
  4. Invoke the judge merger to produce a unified AskMindPackOutput.
  5. Clean up session state.

Data models live in ``schemas.py`` to avoid circular imports.
"""

import asyncio
import json
import logging
import uuid
from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING

from code_muse.plugins.mindpack.memory import ReportStore
from code_muse.plugins.mindpack.schemas import (
    AskMindPackInput,
    AskMindPackOutput,
    ExpertDescriptor,
    MindPackConfig,
    MindPackNestedConfig,
    MindPackRankedOption,
    ProfileDescriptor,
)
from code_muse.plugins.mindpack.schemas import MindPackExpertReport as ExpertReport

if TYPE_CHECKING:
    from code_muse.plugins.mindpack.factory import ExpertAgentFactory
    from code_muse.plugins.mindpack.tools import MindPackInvocationContext

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Expert selector (pluggable strategy)
# ---------------------------------------------------------------------------


class ExpertSelector(ABC):
    """Strategy for choosing which experts to consult given an input."""

    @abstractmethod
    def select(
        self, request: AskMindPackInput, registry: list[ExpertDescriptor]
    ) -> list[ExpertDescriptor]:
        """Return the subset of experts to consult for this request."""


class DefaultExpertSelector(ExpertSelector):
    """Simple selector: returns up to `max_experts` from the registry.

    For now this is a naive top-N slice. Smarter selection (semantic
    matching, relevance scoring) will come in a later epic.
    """

    def select(
        self, request: AskMindPackInput, registry: list[ExpertDescriptor]
    ) -> list[ExpertDescriptor]:
        cap = request.max_experts or len(registry)
        return registry[:cap]


# ---------------------------------------------------------------------------
# Judge merger (pluggable strategy)
# ---------------------------------------------------------------------------


class JudgeMerger(ABC):
    """Strategy for merging expert reports into a final advisory output.

    All implementations must provide the async ``merge`` method.  The
    ``session_id`` parameter allows mergers to log and emit events in the
    correct consultation context.
    """

    @abstractmethod
    async def merge(
        self,
        request: AskMindPackInput,
        reports: list[ExpertReport],
        session_id: str,
    ) -> AskMindPackOutput:
        """Produce a unified advisory from all expert reports."""


class PlaceholderJudgeMerger(JudgeMerger):
    """Minimal placeholder that echoes back a summary without real merging.

    Kept as an explicit opt-out for cases where the LLM judge should
    not be used (e.g. testing, offline mode).  The ``LLMJudgeMerger``
    is the default production implementation.
    """

    async def merge(
        self,
        request: AskMindPackInput,
        reports: list[ExpertReport],
        session_id: str,
    ) -> AskMindPackOutput:
        expert_names = [r.expert_id for r in reports]
        all_risks = [r for report in reports for r in report.risks]
        all_files = [f for report in reports for f in report.files_to_inspect]
        all_recs = [r for report in reports for r in report.proposed_plan]

        return AskMindPackOutput(
            summary=(
                f"Placeholder merger: consulted {len(reports)} expert(s) "
                f"for '{request.desired_output}' on: "
                f"{request.problem_statement[:200]}"
            ),
            recommended_plan="\n".join(all_recs) or "No recommendations produced.",
            ranked_options=[
                MindPackRankedOption(
                    rank=1,
                    title="Placeholder option",
                    source_experts=expert_names,
                    summary="Placeholder merged option — LLM judge not active.",
                )
            ],
            risks=all_risks or ["Placeholder: no risks identified."],
            tests_to_run=[],
            files_to_inspect_or_change=list(dict.fromkeys(all_files)),
            expert_consensus=(f"Placeholder: {len(reports)} expert(s) consulted."),
            disagreements=[],
            confidence=sum(r.confidence for r in reports) / max(len(reports), 1),
        )


# ---------------------------------------------------------------------------
# MindPackOrchestrator
# ---------------------------------------------------------------------------


class MindPackOrchestrator:
    """Manages the lifecycle of a MindPack consultation.

    Typical usage::

        orchestrator = MindPackOrchestrator()
        result = await orchestrator.consult(request)
    """

    def __init__(
        self,
        report_store: ReportStore | None = None,
        expert_selector: ExpertSelector | None = None,
        judge_merger: JudgeMerger | None = None,
        expert_factory: ExpertAgentFactory | None = None,
        config: MindPackConfig | None = None,
    ) -> None:
        self._store = report_store or ReportStore()
        self._selector = expert_selector or DefaultExpertSelector()
        if judge_merger is not None:
            self._merger = judge_merger
        else:
            from code_muse.plugins.mindpack.judge import LLMJudgeMerger

            self._merger = LLMJudgeMerger()
        if expert_factory is not None:
            self._factory = expert_factory
        else:
            from code_muse.plugins.mindpack.factory import ExpertAgentFactory

            self._factory = ExpertAgentFactory()
        self._expert_registry: list[ExpertDescriptor] = []
        self._profile_registry: list[ProfileDescriptor] = []
        self.config: MindPackConfig = config if config is not None else MindPackConfig()

    # -- registry -----------------------------------------------------------

    @staticmethod
    def _get_experts_config_path() -> Path:
        """Return the path to the experts config file."""
        config_dir = Path.home() / ".muse" / "mindpack"
        config_dir.mkdir(parents=True, exist_ok=True)
        return config_dir / "experts.json"

    def save_experts(self) -> None:
        """Persist current expert registry to disk."""
        config_path = self._get_experts_config_path()
        data = [e.model_dump() for e in self._expert_registry]
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        logger.info("Orchestrator: saved %d experts to %s", len(data), config_path)

    def load_experts(self) -> None:
        """Load custom experts from disk, merging with defaults.

        Preserves experts that were registered before this call
        (i.e., the default experts from tools.py).  Custom experts
        from the config file are added, and any experts with the
        same name are replaced.
        """
        config_path = self._get_experts_config_path()
        if not config_path.exists():
            logger.debug("Orchestrator: no custom experts config found")
            return

        try:
            with open(config_path, encoding="utf-8") as f:
                data = json.load(f)

            # Remove any existing experts that will be replaced
            custom_experts = [ExpertDescriptor(**d) for d in data]
            names_to_replace = {e.name for e in custom_experts}
            self._expert_registry = [
                e for e in self._expert_registry if e.name not in names_to_replace
            ]

            # Add custom experts
            self._expert_registry.extend(custom_experts)
            logger.info(
                "Orchestrator: loaded %d custom expert(s) from %s",
                len(custom_experts),
                config_path,
            )
        except Exception as exc:
            logger.error("Orchestrator: failed to load experts config: %s", exc)

    def register_expert(self, expert: ExpertDescriptor) -> None:
        """Add an expert to the available pool."""
        self._expert_registry.append(expert)
        logger.debug("Orchestrator: registered expert '%s'", expert.name)

    def register_experts(self, experts: list[ExpertDescriptor]) -> None:
        """Bulk-register a list of experts."""
        for e in experts:
            self.register_expert(e)

    def remove_expert(self, name: str) -> bool:
        """Remove an expert from the registry by name.

        Returns:
            True if an expert was removed, False if not found.
        """
        original_len = len(self._expert_registry)
        self._expert_registry = [e for e in self._expert_registry if e.name != name]
        removed = len(self._expert_registry) < original_len
        if removed:
            logger.debug("Orchestrator: removed expert '%s'", name)
        return removed

    @property
    def expert_registry(self) -> list[ExpertDescriptor]:
        """Read-only view of the current expert pool.

        When an active profile is set, returns only the experts
        belonging to that profile. Otherwise returns all experts.
        """
        active = self.get_active_profile_name()
        if active:
            return self.get_experts_for_profile(active)
        return list(self._expert_registry)

    # -- active profile ----------------------------------------------------

    @staticmethod
    def _get_active_profile_path() -> Path:
        """Return the path to the active profile marker file."""
        config_dir = Path.home() / ".muse" / "mindpack"
        config_dir.mkdir(parents=True, exist_ok=True)
        return config_dir / "active_profile.txt"

    def get_active_profile_name(self) -> str | None:
        """Return the currently active profile name, or None."""
        path = self._get_active_profile_path()
        if not path.exists():
            return None
        try:
            return path.read_text().strip() or None
        except Exception:
            return None

    def set_active_profile(self, profile_name: str) -> None:
        """Set the active profile name, persisting to disk."""
        path = self._get_active_profile_path()
        path.write_text(profile_name)
        logger.info("Orchestrator: active profile set to '%s'", profile_name)

    def clear_active_profile(self) -> None:
        """Clear the active profile."""
        path = self._get_active_profile_path()
        if path.exists():
            path.unlink()
            logger.info("Orchestrator: active profile cleared")

    # -- profile registry ---------------------------------------------------

    @staticmethod
    def _get_profiles_config_path() -> Path:
        """Return the path to the profiles config file."""
        config_dir = Path.home() / ".muse" / "mindpack"
        config_dir.mkdir(parents=True, exist_ok=True)
        return config_dir / "profiles.json"

    def save_profiles(self) -> None:
        """Persist current profile registry to disk."""
        config_path = self._get_profiles_config_path()
        data = [p.model_dump() for p in self._profile_registry]
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        logger.info("Orchestrator: saved %d profiles to %s", len(data), config_path)

    def load_profiles(self) -> None:
        """Load profiles from disk, seeding defaults on first run.

        On first run (no profiles.json), seeds default profiles.
        Auto-migrates: any experts not referenced by any profile
        get added to the 'Default' profile.
        """
        config_path = self._get_profiles_config_path()
        if not config_path.exists():
            logger.info("Orchestrator: no profiles config found — seeding defaults")
            from code_muse.plugins.mindpack.schemas import _DEFAULT_PROFILES

            self._profile_registry = list(_DEFAULT_PROFILES)
            self._migrate_orphans_to_default()
            self.save_profiles()
            return

        try:
            with open(config_path, encoding="utf-8") as f:
                data = json.load(f)
            self._profile_registry = [ProfileDescriptor(**d) for d in data]
            self._migrate_orphans_to_default()
            logger.info(
                "Orchestrator: loaded %d profile(s) from %s",
                len(self._profile_registry),
                config_path,
            )
        except Exception as exc:
            logger.error("Orchestrator: failed to load profiles config: %s", exc)
            from code_muse.plugins.mindpack.schemas import _DEFAULT_PROFILES

            self._profile_registry = list(_DEFAULT_PROFILES)

    def _migrate_orphans_to_default(self) -> None:
        """Add experts not referenced by any profile to the 'Default' profile."""
        referenced = set()
        for profile in self._profile_registry:
            referenced.update(profile.expert_names)

        orphan_names = [
            e.name for e in self._expert_registry if e.name not in referenced
        ]

        if not orphan_names:
            return

        # Find or create the Default profile
        default = next((p for p in self._profile_registry if p.name == "Default"), None)
        if default is None:
            default = ProfileDescriptor(
                name="Default",
                description="Catch-all for experts not in any other profile",
                expert_names=[],
            )
            self._profile_registry.append(default)

        for name in orphan_names:
            if name not in default.expert_names:
                default.expert_names.append(name)
                logger.debug(
                    "Orchestrator: migrated orphan expert '%s' into Default profile",
                    name,
                )

    def register_profile(self, profile: ProfileDescriptor) -> None:
        """Add a profile to the registry (replaces existing with same name)."""
        self._profile_registry = [
            p for p in self._profile_registry if p.name != profile.name
        ]
        self._profile_registry.append(profile)
        logger.debug("Orchestrator: registered profile '%s'", profile.name)

    def remove_profile(self, name: str) -> bool:
        """Remove a profile by name.

        Returns:
            True if a profile was removed, False if not found.
        """
        original_len = len(self._profile_registry)
        self._profile_registry = [p for p in self._profile_registry if p.name != name]
        removed = len(self._profile_registry) < original_len
        if removed:
            logger.debug("Orchestrator: removed profile '%s'", name)
        return removed

    def get_experts_for_profile(self, profile_name: str) -> list[ExpertDescriptor]:
        """Resolve a profile name to its ExpertDescriptors.

        Returns an empty list if the profile is not found.
        """
        profile = next(
            (p for p in self._profile_registry if p.name == profile_name), None
        )
        if profile is None:
            return []

        expert_map = {e.name: e for e in self._expert_registry}
        return [expert_map[name] for name in profile.expert_names if name in expert_map]

    @property
    def profile_registry(self) -> list[ProfileDescriptor]:
        """Read-only view of the current profile pool."""
        return list(self._profile_registry)

    # -- consultation lifecycle ---------------------------------------------

    async def consult(
        self,
        request: AskMindPackInput,
        invocation_context: MindPackInvocationContext | None = None,
        nested_config: MindPackNestedConfig | None = None,
    ) -> AskMindPackOutput:
        """Run a full consultation cycle.

        1. Generate a session ID.
        2. Select experts from the registry.
        3. Spawn experts and collect reports.
        4. Run the judge merger.
        5. Clean up session data.

        Args:
            request: The consultation input.
            invocation_context: Nested-workflow tracking (depth, call counts).
            nested_config: INI-driven nested limits (timeout, max_depth).

        Returns the merged advisory output.
        """
        session_id = uuid.uuid4().hex[:12]
        if invocation_context is not None:
            logger.info(
                "Orchestrator: nested consultation depth=%d/%d session='%s'",
                invocation_context.nested_depth,
                invocation_context.max_depth,
                session_id,
            )
        logger.info(
            "Orchestrator: starting consultation session='%s' "
            "desired_output='%s' problem='%s'",
            session_id,
            request.desired_output,
            request.problem_statement[:120],
        )

        # Select experts
        selected = self._selector.select(request, self._expert_registry)
        logger.info(
            "Orchestrator: selected %d expert(s) for session '%s': %s",
            len(selected),
            session_id,
            [e.name for e in selected],
        )

        # Spawn experts and collect reports (with optional timeout cap)
        timeout = None
        if nested_config is not None:
            timeout = nested_config.timeout_sec

        try:
            if timeout:
                reports = await asyncio.wait_for(
                    self._spawn_and_collect(session_id, request, selected),
                    timeout=timeout,
                )
            else:
                reports = await self._spawn_and_collect(session_id, request, selected)
        except TimeoutError:
            logger.error(
                "Orchestrator: consultation session='%s' exceeded timeout (%ss)",
                session_id,
                timeout,
            )
            # Return a graceful timeout advisory instead of crashing
            return AskMindPackOutput(
                summary=f"MindPack consultation timed out after {timeout}s.",
                recommended_plan=(
                    "The expert panel did not finish in time. "
                    "Consider simplifying the problem statement or increasing "
                    "packmind_nested_timeout_sec in your config."
                ),
                ranked_options=[],
                risks=[f"Timeout: expert pool exceeded {timeout}s limit"],
                tests_to_run=[],
                files_to_inspect_or_change=[],
                expert_consensus="No consensus — consultation aborted by timeout.",
                disagreements=[],
                confidence=0.0,
            )

        # Merge via judge (async — LLM-backed or placeholder)
        output = await self._merger.merge(request, reports, session_id)

        # Clean up session memory
        self._store.clear_run(session_id)

        logger.info(
            "Orchestrator: consultation complete session='%s' "
            "experts=%d confidence=%.2f",
            session_id,
            len(reports),
            output.confidence,
        )
        return output

    # -- expert spawning (skeleton) -----------------------------------------

    async def _spawn_and_collect(
        self,
        session_id: str,
        request: AskMindPackInput,
        experts: list[ExpertDescriptor],
    ) -> list[ExpertReport]:
        """Spawn each expert agent and collect their reports in parallel.

        Uses the Factory to prepare and run experts concurrently via asyncio.gather.
        """
        if hasattr(self._factory, "invoke_expert"):
            # If the factory doesn't support batching directly, use TaskGroup
            async with asyncio.TaskGroup() as tg:
                tg_tasks = [
                    tg.create_task(self._invoke_expert(session_id, request, expert))
                    for expert in experts
                ]
            results = [t.result() for t in tg_tasks]
            reports = [r for r in results if r is not None]
            for report in reports:
                self._store.add_report(report)
            return reports

        # Fallback to serial for safe implementation if batch API changes
        return await self._spawn_and_collect_serial(session_id, request, experts)

    async def _spawn_and_collect_serial(
        self,
        session_id: str,
        request: AskMindPackInput,
        experts: list[ExpertDescriptor],
    ) -> list[ExpertReport]:
        """Serial fallback for expert invocation."""
        reports: list[ExpertReport] = []
        for expert in experts:
            report = await self._invoke_expert(session_id, request, expert)
            if report is not None:
                self._store.add_report(report)
                reports.append(report)
        return reports

    async def _invoke_expert(
        self,
        session_id: str,
        request: AskMindPackInput,
        expert: ExpertDescriptor,
    ) -> ExpertReport | None:
        """Invoke a single expert via the ExpertAgentFactory.

        The factory creates a read-only sub-agent with the expert's
        system prompt fragment, runs it against the consultation prompt,
        and returns a structured ``ExpertReport``.

        Falls back to a minimal error report if the factory fails entirely.
        """
        logger.info(
            "Orchestrator: invoking expert '%s' for session '%s'",
            expert.name,
            session_id,
        )

        try:
            report = await self._factory.invoke_expert(expert, request, session_id)
        except Exception as exc:
            logger.error(
                "Orchestrator: expert '%s' raised unexpected error: %s",
                expert.name,
                exc,
                exc_info=True,
            )
            report = ExpertReport(
                expert_id=expert.name,
                run_id=session_id,
                lens="error",
                prompt_variant="fallback",
                summary=f"[Error] Unexpected failure: {exc}",
                findings=[],
                proposed_plan=[],
                risks=[f"Expert invocation raised: {exc}"],
                files_to_inspect=[],
                confidence=0.0,
                status="failed",
            )

        return report

    # -- cleanup ------------------------------------------------------------

    async def shutdown(self) -> None:
        """Graceful shutdown — clear all session data."""
        self._store.clear_all()
        logger.info("Orchestrator: shutdown complete")
