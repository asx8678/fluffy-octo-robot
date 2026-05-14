"""MindPack memory — ReportStore for expert report buffering.

Provides a structured, flexible storage system for expert reports.
Supports in-memory buffering, persistent caching, and workspace-local storage.
"""

import orjson as json
import logging
import pathlib

from pydantic import BaseModel

from code_muse.plugins.mindpack.schemas import (
    MindPackExpertReport,
    MindPackMergedDecision,
    MindPackReportStoreConfig,
    ReportStoreMode,
)
from code_muse.security.redaction import redact_secrets

logger = logging.getLogger(__name__)


class ReportStore:
    """Manages storage for MindPack expert reports and final decisions."""

    def __init__(self, config: MindPackReportStoreConfig | None = None) -> None:
        self.config = config or MindPackReportStoreConfig()
        self._memory_store: dict[str, list[MindPackExpertReport]] = {}
        self._decisions: dict[str, MindPackMergedDecision] = {}

    def _get_storage_path(
        self, run_id: str, mode: ReportStoreMode
    ) -> pathlib.Path | None:
        if mode == "cache":
            path = pathlib.Path(self.config.cache_dir).expanduser() / run_id
            path.mkdir(parents=True, exist_ok=True)
            return path
        elif mode == "workspace":
            path = pathlib.Path.cwd() / self.config.workspace_dir / run_id
            path.mkdir(parents=True, exist_ok=True)
            return path
        return None

    def _save_to_disk(self, run_id: str, data: BaseModel, filename: str) -> None:
        """Helper to save serializable data to disk."""
        modes = (
            [self.config.mode] if self.config.mode != "both" else ["cache", "workspace"]
        )
        for mode in modes:
            path = self._get_storage_path(run_id, mode)  # type: ignore
            if path:
                file_path = path / filename
                data_dict = data.model_dump()
                if not self.config.save_raw_transcripts:
                    data_dict = redact_secrets(data_dict)
                with open(file_path, "w") as f:
                    f.write(orjson.dumps(data_dict, option=orjson.OPT_INDENT_2).decode())
                logger.debug("ReportStore: saved %s to %s", filename, file_path)

    def add_report(self, report: MindPackExpertReport) -> None:
        """Stores a report in memory and optionally persists it."""
        if self.config.mode in ["memory", "both"]:
            if report.run_id not in self._memory_store:
                self._memory_store[report.run_id] = []
            self._memory_store[report.run_id].append(report)

        if self.config.mode in ["cache", "workspace", "both"]:
            self._save_to_disk(report.run_id, report, f"report_{report.expert_id}.json")

    def save_reports(self, reports: list[MindPackExpertReport]) -> None:
        """Batch save reports."""
        for report in reports:
            self.add_report(report)

    def save_merged_decision(self, merged: MindPackMergedDecision) -> None:
        """Stores and persists the final judge decision."""
        self._decisions[merged.run_id] = merged
        if self.config.mode in ["cache", "workspace", "both"]:
            self._save_to_disk(merged.run_id, merged, "decision.json")

    def get_reports(self, run_id: str) -> list[MindPackExpertReport]:
        """Fetch reports from memory."""
        return self._memory_store.get(run_id, [])

    def clear_run(self, run_id: str) -> None:
        """Clears memory for a run."""
        self._memory_store.pop(run_id, None)
        self._decisions.pop(run_id, None)
        logger.debug("ReportStore: cleared run '%s'", run_id)

    def report_count(self, run_id: str) -> int:
        """Return the number of reports buffered for a run."""
        return len(self._memory_store.get(run_id, []))

    def clear_all(self) -> None:
        """Clears all buffered memory and decisions."""
        self._memory_store.clear()
        self._decisions.clear()
        logger.debug("ReportStore: cleared all runs")
