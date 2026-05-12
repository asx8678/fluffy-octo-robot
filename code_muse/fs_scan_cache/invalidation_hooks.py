"""Invalidation hooks that clear ScanCache on file mutations."""

import logging
import os
from pathlib import Path
from typing import Any

from code_muse.callbacks import register_callback
from code_muse.fs_scan_cache.scan_cache_core import ScanCache

logger = logging.getLogger(__name__)

_cache: ScanCache | None = None


def _extract_path_from_tool_args(
    tool_name: str, tool_args: dict[str, Any]
) -> str | None:
    """Try to extract the affected file path from known tool signatures."""
    if tool_name in {"write_file", "replace_in_file", "delete_file", "delete_snippet"}:
        # These tools typically have a ``file_path`` argument
        candidate = tool_args.get("file_path")
        if candidate:
            return str(candidate)
    # Fallback: look for any key that smells like a path
    for key in ("path", "file_path", "directory", "root"):
        candidate = tool_args.get(key)
        if candidate and isinstance(candidate, str):
            # Heuristic: does it look like a filesystem path?
            if os.sep in candidate or candidate.startswith(".") or "/" in candidate:
                return candidate
    return None


async def _on_post_tool_call(
    tool_name: str,
    tool_args: dict[str, Any],
    result: Any,
    duration_ms: float,
    context: Any = None,
) -> None:
    """Invalidate cache entries when a file-mutating tool completes."""
    global _cache

    if _cache is None:
        return

    if tool_name not in {
        "write_file",
        "replace_in_file",
        "delete_file",
        "delete_snippet",
    }:
        return

    modified_path = _extract_path_from_tool_args(tool_name, tool_args)
    if not modified_path:
        logger.debug(f"No path extracted for {tool_name}; skipping invalidation")
        return

    # For delete_file, invalidate the parent directory because the file no
    # longer exists and we don't want stale directory listings.
    if tool_name == "delete_file":
        parent = Path(modified_path).parent
        try:
            resolved = parent.resolve()
        except OSError:
            resolved = parent.absolute()
        _cache.invalidate_for_path(str(resolved))
        logger.debug(f"ScanCache invalidated parent of deleted file: {resolved}")
    else:
        try:
            resolved = Path(modified_path).resolve()
        except OSError:
            resolved = Path(modified_path).absolute()
        _cache.invalidate_for_path(str(resolved))
        logger.debug(f"ScanCache invalidated path after {tool_name}: {resolved}")


def register_invalidation_hooks(cache: ScanCache) -> None:
    """Register ``post_tool_call`` callbacks that invalidate *cache* on writes.

    Args:
        cache: The :class:`ScanCache` instance to keep in sync.
    """
    global _cache
    _cache = cache
    register_callback("post_tool_call", _on_post_tool_call)
    logger.debug("ScanCache invalidation hooks registered")
