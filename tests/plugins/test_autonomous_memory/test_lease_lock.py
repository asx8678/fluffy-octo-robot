"""Tests for the memory lease lock."""

import json
import os
from pathlib import Path

from code_muse.plugins.autonomous_memory.lease_lock import (
    LeaseHandle,
    acquire_memory_lease,
    release_lease,
)


def test_acquire_and_release(tmp_path: Path) -> None:
    """Basic acquire → release cycle."""
    lease = acquire_memory_lease(tmp_path, timeout_minutes=30)
    assert lease is not None
    assert lease.lock_path.exists()
    assert lease.pid == os.getpid()

    release_lease(lease)
    assert not lease.lock_path.exists()


def test_concurrent_prevention(tmp_path: Path) -> None:
    """Second acquire from same PID within timeout returns None."""
    lease1 = acquire_memory_lease(tmp_path, timeout_minutes=30)
    assert lease1 is not None

    lease2 = acquire_memory_lease(tmp_path, timeout_minutes=30)
    assert lease2 is None

    release_lease(lease1)


def test_break_stale_lease(tmp_path: Path) -> None:
    """A lease held by a non-running PID can be stolen."""
    lock_path = tmp_path / ".memory_lease"
    fake_pid = 999_999  # Unlikely to exist
    lock_path.write_text(json.dumps({"pid": fake_pid, "acquired_at": 1.0}))

    lease = acquire_memory_lease(tmp_path, timeout_minutes=30)
    assert lease is not None
    assert lease.pid == os.getpid()
    release_lease(lease)


def test_break_expired_lease(tmp_path: Path) -> None:
    """A lease held by a running PID but past timeout can be stolen."""
    lock_path = tmp_path / ".memory_lease"
    # Use current PID but ancient acquired_at
    lock_path.write_text(json.dumps({"pid": os.getpid(), "acquired_at": 1.0}))

    lease = acquire_memory_lease(tmp_path, timeout_minutes=1)
    assert lease is not None
    release_lease(lease)


def test_release_pid_mismatch(tmp_path: Path) -> None:
    """Releasing a lease with mismatched PID is a no-op."""
    lock_path = tmp_path / ".memory_lease"
    lock_path.write_text(json.dumps({"pid": os.getpid(), "acquired_at": 1.0}))

    fake_handle = LeaseHandle(lock_path=lock_path, pid=123_456, acquired_at=1.0)
    release_lease(fake_handle)
    assert lock_path.exists()


def test_release_missing_file() -> None:
    """Releasing a non-existent lock is a no-op."""
    fake_path = Path("/nonexistent/.memory_lease")
    handle = LeaseHandle(lock_path=fake_path, pid=os.getpid(), acquired_at=1.0)
    release_lease(handle)  # should not raise
