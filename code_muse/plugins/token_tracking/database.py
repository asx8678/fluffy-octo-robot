"""SQLite tracking database for token usage history.

Stores every command execution with raw vs compressed token counts,
enabling gain reports and economics analysis.
"""

import contextlib
import logging
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

SCHEMA_V1 = """
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY
);
INSERT OR IGNORE INTO schema_version VALUES (1);

CREATE TABLE IF NOT EXISTS executions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    command TEXT NOT NULL,
    category TEXT NOT NULL,
    strategy TEXT NOT NULL,
    raw_tokens INTEGER NOT NULL,
    compressed_tokens INTEGER NOT NULL,
    savings_pct REAL NOT NULL,
    timestamp TEXT NOT NULL,
    session_id TEXT NOT NULL,
    exit_code INTEGER,
    duration_ms REAL
);
CREATE INDEX IF NOT EXISTS idx_executions_timestamp ON executions(timestamp);
CREATE INDEX IF NOT EXISTS idx_executions_session ON executions(session_id);
"""

SCHEMA_MIGRATION_V2 = """
ALTER TABLE schema_version ADD COLUMN migration_v2 INTEGER DEFAULT 0;
INSERT OR IGNORE INTO schema_version (version, migration_v2) VALUES (2, 1);

CREATE TABLE IF NOT EXISTS edit_analysis (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tool_name TEXT NOT NULL,
    file_path TEXT NOT NULL,
    old_bytes INTEGER,
    new_bytes INTEGER,
    total_edit_bytes INTEGER,
    shared_prefix_bytes INTEGER,
    shared_suffix_bytes INTEGER,
    shared_context_bytes INTEGER,
    core_old_bytes INTEGER,
    core_new_bytes INTEGER,
    core_bytes INTEGER,
    wrapper_payload_bytes INTEGER,
    inflation_ratio REAL,
    no_core_change INTEGER DEFAULT 0,
    success INTEGER DEFAULT 1,
    timestamp TEXT NOT NULL,
    session_id TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_edit_analysis_timestamp ON edit_analysis(timestamp);
CREATE INDEX IF NOT EXISTS idx_edit_analysis_session ON edit_analysis(session_id);
"""


class TrackingDatabase:
    """Thread-safe SQLite database for tracking command executions.

    Uses WAL mode for concurrency and a single shared connection
    protected by a threading lock.

    This is a plain class. For the shared application instance use
    :func:`get_tracking_db`.
    """

    DB_PATH: Path = Path.home() / ".muse" / "tracking.db"
    _CLEANUP_EVERY_N = 100

    def __init__(self, db_path: Path | str | None = None) -> None:
        """Initialise (or connect to) the tracking database.

        Args:
            db_path: Override the default ``~/.muse/tracking.db``.
        """
        self._db_path = Path(db_path) if db_path is not None else self.DB_PATH
        self._connection: sqlite3.Connection | None = None
        self._lock = threading.Lock()
        self._insert_count = 0
        self._ensure_dir()
        self._run_migrations()
        self.cleanup()

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    def _ensure_dir(self) -> None:
        """Create the parent directory if it doesn't exist."""
        self._db_path.parent.mkdir(parents=True, exist_ok=True)

    def get_connection(self) -> sqlite3.Connection:
        """Lazy-initialise and return the shared connection."""
        if self._connection is None:
            with self._lock:
                if self._connection is None:
                    self._connection = sqlite3.connect(
                        str(self._db_path),
                        check_same_thread=False,
                    )
                    self._connection.execute("PRAGMA journal_mode=WAL")
                    self._connection.execute("PRAGMA foreign_keys=ON")
        return self._connection

    def close(self) -> None:
        """Close the shared connection (idempotent)."""
        with self._lock:
            if self._connection is not None:
                with contextlib.suppress(Exception):
                    self._connection.close()
                self._connection = None

    # ------------------------------------------------------------------
    # Migrations
    # ------------------------------------------------------------------

    def _run_migrations(self) -> None:
        """Ensure schema is at the latest version."""
        conn = self.get_connection()
        with self._lock:
            # Check if schema_version table exists (v1 baseline)
            try:
                conn.execute("SELECT version FROM schema_version LIMIT 1").fetchone()
            except sqlite3.OperationalError:
                # First install — run full schema
                conn.executescript(SCHEMA_V1)
                conn.commit()

            # Check v2 migration
            try:
                conn.execute(
                    "SELECT migration_v2 FROM schema_version LIMIT 1"
                ).fetchone()
            except sqlite3.OperationalError:
                conn.executescript(SCHEMA_MIGRATION_V2)
                conn.commit()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def insert(
        self,
        command: str,
        category: str,
        strategy: str,
        raw_tokens: int,
        compressed_tokens: int,
        savings_pct: float,
        session_id: str,
        exit_code: int = 0,
        duration_ms: float = 0.0,
    ) -> int:
        """Record a command execution.

        Returns:
            The new row id, or ``-1`` on error (never raises).
        """
        try:
            timestamp = datetime.now(UTC).isoformat()
            conn = self.get_connection()
            with self._lock:
                cursor = conn.execute(
                    """
                    INSERT INTO executions
                    (command, category, strategy, raw_tokens, compressed_tokens,
                     savings_pct, timestamp, session_id, exit_code, duration_ms)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        command,
                        category,
                        strategy,
                        raw_tokens,
                        compressed_tokens,
                        savings_pct,
                        timestamp,
                        session_id,
                        exit_code,
                        duration_ms,
                    ),
                )
                conn.commit()
                row_id = cursor.lastrowid or -1

            self._insert_count += 1
            if self._insert_count % self._CLEANUP_EVERY_N == 0:
                self.cleanup()
            return row_id
        except Exception as exc:
            logger.warning("TrackingDatabase insert failed: %s", exc)
            return -1

    def insert_edit_analysis(
        self,
        tool_name: str,
        file_path: str,
        old_bytes: int,
        new_bytes: int,
        total_edit_bytes: int,
        shared_prefix_bytes: int,
        shared_suffix_bytes: int,
        shared_context_bytes: int,
        core_old_bytes: int,
        core_new_bytes: int,
        core_bytes: int,
        wrapper_payload_bytes: int,
        inflation_ratio: float | None,
        no_core_change: bool,
        success: bool = True,
        session_id: str = "",
    ) -> int:
        """Record an edit operation analysis. Returns row id or -1."""
        try:
            timestamp = datetime.now(UTC).isoformat()
            conn = self.get_connection()
            with self._lock:
                cursor = conn.execute(
                    """
                    INSERT INTO edit_analysis
                    (tool_name, file_path, old_bytes, new_bytes, total_edit_bytes,
                     shared_prefix_bytes, shared_suffix_bytes, shared_context_bytes,
                     core_old_bytes, core_new_bytes, core_bytes, wrapper_payload_bytes,
                     inflation_ratio, no_core_change, success, timestamp, session_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        tool_name,
                        file_path,
                        old_bytes,
                        new_bytes,
                        total_edit_bytes,
                        shared_prefix_bytes,
                        shared_suffix_bytes,
                        shared_context_bytes,
                        core_old_bytes,
                        core_new_bytes,
                        core_bytes,
                        wrapper_payload_bytes,
                        inflation_ratio,
                        1 if no_core_change else 0,
                        1 if success else 0,
                        timestamp,
                        session_id,
                    ),
                )
                conn.commit()
                return cursor.lastrowid or -1
        except Exception as exc:
            logger.warning("TrackingDatabase insert_edit_analysis failed: %s", exc)
            return -1

    def query_edit_summary(self, time_range: str = "all") -> list[dict]:
        """Get edit efficiency summary for the given time range.

        Returns a list of dicts, one per edit_analysis row.
        """
        where = {
            "today": "date(timestamp) = date('now')",
            "week": "timestamp >= datetime('now', '-7 days')",
            "month": "timestamp >= datetime('now', '-30 days')",
            "all": "1=1",
        }.get(time_range, "1=1")

        conn = self.get_connection()
        with self._lock:
            rows = conn.execute(
                # TODO: PEP 750 t-string — use templatelib when stable
                f"""
                SELECT
                    id, tool_name, file_path, old_bytes, new_bytes,
                    total_edit_bytes, shared_prefix_bytes, shared_suffix_bytes,
                    shared_context_bytes, core_old_bytes, core_new_bytes,
                    core_bytes, wrapper_payload_bytes, inflation_ratio,
                    no_core_change, success, timestamp, session_id
                FROM edit_analysis
                WHERE {where}
                ORDER BY timestamp DESC
                """,
            ).fetchall()

        columns = [
            "id",
            "tool_name",
            "file_path",
            "old_bytes",
            "new_bytes",
            "total_edit_bytes",
            "shared_prefix_bytes",
            "shared_suffix_bytes",
            "shared_context_bytes",
            "core_old_bytes",
            "core_new_bytes",
            "core_bytes",
            "wrapper_payload_bytes",
            "inflation_ratio",
            "no_core_change",
            "success",
            "timestamp",
            "session_id",
        ]
        return [dict(zip(columns, row, strict=False)) for row in rows]

    def cleanup(self, retention_days: int = 90) -> int:
        """Delete records older than *retention_days*.

        Returns:
            Number of rows deleted.
        """
        try:
            conn = self.get_connection()
            with self._lock:
                cursor = conn.execute(
                    """
                    DELETE FROM executions
                    WHERE timestamp < datetime('now', ?)
                    """,
                    (f"-{retention_days} days",),
                )
                cursor2 = conn.execute(
                    """
                    DELETE FROM edit_analysis
                    WHERE timestamp < datetime('now', ?)
                    """,
                    (f"-{retention_days} days",),
                )
                conn.commit()
                return cursor.rowcount + cursor2.rowcount
        except Exception as exc:
            logger.warning("TrackingDatabase cleanup failed: %s", exc)
            return 0

    # ------------------------------------------------------------------
    # Query helpers
    # ------------------------------------------------------------------

    def query_one(self, sql: str, parameters: tuple[Any, ...] = ()) -> Any:
        """Execute a query and return the first row (or None)."""
        conn = self.get_connection()
        with self._lock:
            return conn.execute(sql, parameters).fetchone()

    def query_all(self, sql: str, parameters: tuple[Any, ...] = ()) -> list[Any]:
        """Execute a query and return all rows."""
        conn = self.get_connection()
        with self._lock:
            return conn.execute(sql, parameters).fetchall()


# Module-level singleton cache — simple, testable, explicit.
_tracking_db_instance: TrackingDatabase | None = None
_tracking_db_lock = threading.Lock()


def get_tracking_db(db_path: Path | str | None = None) -> TrackingDatabase:
    """Return the shared :class:`TrackingDatabase` instance.

    The first call creates and caches the instance; subsequent calls
    return the same object. Thread-safe.

    Args:
        db_path: Override the default ``~/.muse/tracking.db``.
    """
    global _tracking_db_instance
    if _tracking_db_instance is None:
        with _tracking_db_lock:
            if _tracking_db_instance is None:
                _tracking_db_instance = TrackingDatabase(db_path)
    return _tracking_db_instance
