"""TTL policy for ScanCache entries."""

import os
import typing

if typing.TYPE_CHECKING:
    from code_muse.fs_scan_cache.scan_cache_core import ScanEntry


def env_uint(name: str, default: int) -> int:
    """Read an unsigned integer from an environment variable.

    Returns *default* if the variable is missing, empty, or not a valid
    non-negative integer.
    """
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value >= 0 else default


CACHE_TTL_MS: int = env_uint("FS_SCAN_CACHE_TTL_MS", 1000)
EMPTY_RECHECK_MS: int = env_uint("FS_SCAN_EMPTY_RECHECK_MS", 200)


def is_fresh(entry: ScanEntry, now: float) -> bool:
    """Return ``True`` if *entry* has not exceeded its TTL.

    Rules:
    * If ``CACHE_TTL_MS == 0``: always stale (cache bypass).
    * If *entry* has no items: age must be < ``EMPTY_RECHECK_MS``.
    * If *entry* has items: age must be < ``CACHE_TTL_MS``.
    """
    if CACHE_TTL_MS == 0:
        return False

    age_ms = (now - entry.created_at) * 1000.0
    if not entry.entries:
        return age_ms < EMPTY_RECHECK_MS
    return age_ms < CACHE_TTL_MS
