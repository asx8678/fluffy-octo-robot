"""Lease-based lock for the Autonomous Memory Pipeline.

Prevents concurrent memory extraction / consolidation jobs from
stepping on each other across multiple processes.
"""

import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path

import orjson as json

logger = logging.getLogger(__name__)


def _is_pid_running(pid: int) -> bool:
    """Return ``True`` if process ``pid`` is alive."""
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    else:
        return True


@dataclass
class LeaseHandle:
    """Token representing a held memory lease."""

    lock_path: Path
    pid: int
    acquired_at: float


def acquire_memory_lease(
    memory_dir: Path, timeout_minutes: int = 30
) -> LeaseHandle | None:
    """Attempt to acquire the memory-processing lease.

    Returns a :class:`LeaseHandle` on success, or ``None`` if the lease
    is already held by a living process within the timeout window.
    """
    memory_dir.mkdir(parents=True, exist_ok=True)
    lock_path = memory_dir / ".memory_lease"

    # Check for existing lease
    if lock_path.exists():
        try:
            with lock_path.open("r", encoding="utf-8") as fh:
                data = json.loads(fh.read())
            old_pid = int(data.get("pid", 0))
            acquired_at = float(data.get("acquired_at", 0))
        except Exception:
            old_pid = 0
            acquired_at = 0

        now = time.time()
        expired = (now - acquired_at) > (timeout_minutes * 60)

        if old_pid and _is_pid_running(old_pid) and not expired:
            logger.debug(f"Memory lease held by PID {old_pid}")
            return None

        # Stale lease — break it
        try:
            lock_path.unlink()
            logger.debug("Broke stale memory lease")
        except OSError as exc:
            logger.warning(f"Could not remove stale lock {lock_path}: {exc}")
            return None

    # Write new lease
    my_pid = os.getpid()
    acquired_at = time.time()
    try:
        with lock_path.open("w", encoding="utf-8") as fh:
            fh.write(json.dumps({"pid": my_pid, "acquired_at": acquired_at}).decode())
    except OSError as exc:
        logger.warning(f"Could not write memory lease {lock_path}: {exc}")
        return None

    return LeaseHandle(lock_path=lock_path, pid=my_pid, acquired_at=acquired_at)


def release_lease(handle: LeaseHandle) -> None:
    """Release a previously acquired memory lease."""
    if not handle.lock_path.exists():
        return

    try:
        with handle.lock_path.open("r", encoding="utf-8") as fh:
            data = json.loads(fh.read())
        current_pid = int(data.get("pid", 0))
    except Exception:
        current_pid = 0

    if current_pid == handle.pid:
        try:
            handle.lock_path.unlink()
            logger.debug("Released memory lease")
        except OSError as exc:
            logger.warning(f"Could not release lease {handle.lock_path}: {exc}")
    else:
        logger.debug("Lease PID mismatch; not releasing")
