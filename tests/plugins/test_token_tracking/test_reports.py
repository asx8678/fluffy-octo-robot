"""Tests for the token tracking reports module."""

from pathlib import Path

from code_muse.plugins.token_tracking.database import TrackingDatabase
from code_muse.plugins.token_tracking.reports import (
    cc_economics_report,
    gain_report,
    session_report,
)


class TestGainReport:
    """Token savings reports."""

    def test_empty_db(self, tmp_path: Path) -> None:
        db = TrackingDatabase(db_path=tmp_path / "tracking.db")
        report = gain_report(db, "all")
        assert "Token Savings Report" in report
        assert "no data" in report

    def test_today_range(self, tmp_path: Path) -> None:
        db = TrackingDatabase(db_path=tmp_path / "tracking.db")
        db.insert(
            command="git status",
            category="git",
            strategy="compress_git_status",
            raw_tokens=100,
            compressed_tokens=50,
            savings_pct=50.0,
            session_id="sess-1",
        )
        report = gain_report(db, "today")
        assert "Savings: 50 tokens" in report
        assert "compress_git_status" in report

    def test_top_strategies_shown(self, tmp_path: Path) -> None:
        db = TrackingDatabase(db_path=tmp_path / "tracking.db")
        for i in range(6):
            db.insert(
                command=f"cmd{i}",
                category="git",
                strategy=f"strategy_{i}",
                raw_tokens=100,
                compressed_tokens=10,
                savings_pct=90.0,
                session_id="sess-1",
            )
        report = gain_report(db, "all")
        # Should show top 5 only
        lines = report.splitlines()
        strategy_lines = [
            line for line in lines if line.strip().startswith("strategy_")
        ]
        assert len(strategy_lines) == 5


class TestCcEconomicsReport:
    """Claude Code economics reports."""

    def test_empty_db(self, tmp_path: Path) -> None:
        db = TrackingDatabase(db_path=tmp_path / "tracking.db")
        report = cc_economics_report(db, "all")
        assert "Claude Code Economics Report" in report
        assert "$0.0000" in report

    def test_savings_calculated(self, tmp_path: Path) -> None:
        db = TrackingDatabase(db_path=tmp_path / "tracking.db")
        db.insert(
            command="git status",
            category="git",
            strategy="compress_git_status",
            raw_tokens=1_000_000,
            compressed_tokens=500_000,
            savings_pct=50.0,
            session_id="sess-1",
        )
        report = cc_economics_report(db, "all")
        assert "Uncompressed input cost: $3.0000" in report
        assert "Compressed input cost:   $1.5000" in report
        assert "Estimated savings:       $1.5000" in report


class TestSessionReport:
    """Per-session adoption reports."""

    def test_empty_db(self, tmp_path: Path) -> None:
        db = TrackingDatabase(db_path=tmp_path / "tracking.db")
        report = session_report(db, 10)
        assert "Session Report" in report
        assert "no tracking data" in report

    def test_single_session(self, tmp_path: Path) -> None:
        db = TrackingDatabase(db_path=tmp_path / "tracking.db")
        db.insert(
            command="git status",
            category="git",
            strategy="compress_git_status",
            raw_tokens=100,
            compressed_tokens=50,
            savings_pct=50.0,
            session_id="sess-abc",
        )
        db.insert(
            command="echo hi",
            category="unknown",
            strategy="unknown",
            raw_tokens=10,
            compressed_tokens=10,
            savings_pct=0.0,
            session_id="sess-abc",
        )
        report = session_report(db, 10)
        assert "sess-abc"[:8] in report
        assert "Commands: 2 total, 1 filtered" in report
        assert "Adoption: 50.0%" in report

    def test_low_adoption_warning(self, tmp_path: Path) -> None:
        db = TrackingDatabase(db_path=tmp_path / "tracking.db")
        db.insert(
            command="echo hi",
            category="unknown",
            strategy="unknown",
            raw_tokens=10,
            compressed_tokens=10,
            savings_pct=0.0,
            session_id="sess-low",
        )
        report = session_report(db, 10)
        assert "low adoption" in report
