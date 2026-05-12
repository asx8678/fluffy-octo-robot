"""Filesystem Scan Cache — TTL-based directory entry cache for glob/grep/find."""

from code_muse.fs_scan_cache.scan_cache_core import (
    CacheStats,
    GlobMatch,
    ScanCache,
)
from code_muse.fs_scan_cache.tool_integration import (
    cached_find,
    cached_glob,
    cached_grep,
)
from code_muse.fs_scan_cache.ttl_policy import (
    CACHE_TTL_MS,
    EMPTY_RECHECK_MS,
    env_uint,
    is_fresh,
)

__all__ = [
    "CacheStats",
    "GlobMatch",
    "ScanCache",
    "cached_glob",
    "cached_grep",
    "cached_find",
    "CACHE_TTL_MS",
    "EMPTY_RECHECK_MS",
    "env_uint",
    "is_fresh",
]
