"""Tests for the token tracking database module."""

import sqlite3
from pathlib import Path
from unittest.mock import patch

from code_muse.plugins.token_tracking.database import (
    TrackingDatabase,
    get_tracking_db,
)


class TestDatabaseLifecycle:
    """Connection, migration, and cleanup."""

    def test_eager_connection(self, tmp_path: Path) -> None:
        db = TrackingDatabase(db_path=tmp_path / "tracking.db")
        # Constructor runs migrations which eagerly creates the connection
        assert db._connection is not None
        conn = db.get_connection()
        assert conn is not None

    def test_creates_directory(self, tmp_path: Path) -> None:
        nested = tmp_path / "deep" / "dir" / "tracking.db"
        db = TrackingDatabase(db_path=nested)
        db.get_connection()
        assert nested.parent.exists()

    def test_schema_version_table(self, tmp_path: Path) -> None:
        db = TrackingDatabase(db_path=tmp_path / "tracking.db")
        row = db.query_one("SELECT version FROM schema_version LIMIT 1")
        assert row is not None
        assert row[0] == 1

    def test_executions_table_exists(self, tmp_path: Path) -> None:
        db = TrackingDatabase(db_path=tmp_path / "tracking.db")
        tables = db.query_all(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='executions'"
        )
        assert len(tables) == 1

    def test_indexes_created(self, tmp_path: Path) -> None:
        db = TrackingDatabase(db_path=tmp_path / "tracking.db")
        indexes = db.query_all(
            "SELECT name FROM sqlite_master "
            "WHERE type='index' AND tbl_name='executions'"
        )
        index_names = {i[0] for i in indexes}
        assert "idx_executions_timestamp" in index_names
        assert "idx_executions_session" in index_names

    def test_wal_mode(self, tmp_path: Path) -> None:
        db = TrackingDatabase(db_path=tmp_path / "tracking.db")
        conn = db.get_connection()
        journal = conn.execute("PRAGMA journal_mode").fetchone()
        assert journal[0].lower() == "wal"

    def test_close_idempotent(self, tmp_path: Path) -> None:
        db = TrackingDatabase(db_path=tmp_path / "tracking.db")
        db.get_connection()
        db.close()
        db.close()  # should not raise
        assert db._connection is None

    def test_factory_same_instance(self, tmp_path: Path) -> None:
        mod = "code_muse.plugins.token_tracking.database"
        with patch(f"{mod}._tracking_db_instance", None):
            db1 = get_tracking_db(db_path=tmp_path / "tracking.db")
            db2 = get_tracking_db(db_path=tmp_path / "tracking.db")
            assert db1 is db2
            assert db1._lock is db2._lock

    def test_plain_class_not_singleton(self, tmp_path: Path) -> None:
        db1 = TrackingDatabase(db_path=tmp_path / "a.db")
        db2 = TrackingDatabase(db_path=tmp_path / "b.db")
        assert db1 is not db2

    def test_factory_init_once(self, tmp_path: Path) -> None:
        mod = "code_muse.plugins.token_tracking.database"
        with patch(f"{mod}._tracking_db_instance", None):
            db1 = get_tracking_db(db_path=tmp_path / "tracking.db")
            db1._insert_count = 42
            db2 = get_tracking_db(db_path=tmp_path / "tracking.db")
            assert db2._insert_count == 42


class TestInsert:
    """Recording executions."""

    def test_insert_returns_row_id(self, tmp_path: Path) -> None:
        db = TrackingDatabase(db_path=tmp_path / "tracking.db")
        row_id = db.insert(
            command="git status",
            category="git",
            strategy="compress_git_status",
            raw_tokens=100,
            compressed_tokens=50,
            savings_pct=50.0,
            session_id="sess-123",
            exit_code=0,
            duration_ms=12.3,
        )
        assert row_id > 0

    def test_insert_never_raises(self, tmp_path: Path) -> None:
        db = TrackingDatabase(db_path=tmp_path / "tracking.db")
        with patch.object(db, "get_connection", side_effect=sqlite3.Error("locked")):
            row_id = db.insert(
                command="git status",
                category="git",
                strategy="compress_git_status",
                raw_tokens=100,
                compressed_tokens=50,
                savings_pct=50.0,
                session_id="sess-123",
            )
        assert row_id == -1

    def test_inserted_data_retrievable(self, tmp_path: Path) -> None:
        db = TrackingDatabase(db_path=tmp_path / "tracking.db")
        db.insert(
            command="pytest",
            category="test",
            strategy="compact_pytest",
            raw_tokens=200,
            compressed_tokens=80,
            savings_pct=60.0,
            session_id="sess-456",
            exit_code=1,
            duration_ms=45.0,
        )
        rows = db.query_all("SELECT command, category, strategy FROM executions")
        assert len(rows) == 1
        assert rows[0] == ("pytest", "test", "compact_pytest")


class TestCleanup:
    """Retention cleanup."""

    def test_cleanup_removes_old_records(self, tmp_path: Path) -> None:
        db = TrackingDatabase(db_path=tmp_path / "tracking.db")
        # Insert an old record manually
        db.get_connection().execute(
            """
            INSERT INTO executions
            (command, category, strategy, raw_tokens, compressed_tokens,
             savings_pct, timestamp, session_id, exit_code, duration_ms)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "old",
                "git",
                "strat",
                1,
                1,
                0.0,
                "2020-01-01T00:00:00+00:00",
                "sess",
                0,
                0.0,
            ),
        )
        db.get_connection().commit()

        removed = db.cleanup(retention_days=1)
        assert removed == 1

    def test_cleanup_keeps_recent_records(self, tmp_path: Path) -> None:
        db = TrackingDatabase(db_path=tmp_path / "tracking.db")
        db.insert(
            command="new",
            category="git",
            strategy="strat",
            raw_tokens=1,
            compressed_tokens=1,
            savings_pct=0.0,
            session_id="sess",
        )
        removed = db.cleanup(retention_days=90)
        assert removed == 0

    def test_cleanup_never_raises(self, tmp_path: Path) -> None:
        db = TrackingDatabase(db_path=tmp_path / "tracking.db")
        with patch.object(db, "get_connection", side_effect=sqlite3.Error("locked")):
            removed = db.cleanup()
        assert removed == 0


class TestQueryHelpers:
    """query_one and query_all."""

    def test_query_one_none_when_empty(self, tmp_path: Path) -> None:
        db = TrackingDatabase(db_path=tmp_path / "tracking.db")
        assert db.query_one("SELECT * FROM executions") is None

    def test_query_all_empty_list(self, tmp_path: Path) -> None:
        db = TrackingDatabase(db_path=tmp_path / "tracking.db")
        assert db.query_all("SELECT * FROM executions") == []
