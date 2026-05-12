"""Tests for invalidation hooks."""

import asyncio
import threading
from typing import Any
from unittest.mock import MagicMock

from code_muse.fs_scan_cache.scan_cache_core import ScanCache

from code_muse.fs_scan_cache.invalidation_hooks import (
    _extract_path_from_tool_args,
    _on_post_tool_call,
    register_invalidation_hooks,
)


def _run(coro: Any) -> Any:
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def test_extract_path_write_file() -> None:
    args = {"file_path": "/project/src/main.py", "content": "x"}
    assert _extract_path_from_tool_args("write_file", args) == "/project/src/main.py"


def test_extract_path_replace_in_file() -> None:
    args = {"file_path": "/project/src/main.py", "old_str": "a", "new_str": "b"}
    assert (
        _extract_path_from_tool_args("replace_in_file", args) == "/project/src/main.py"
    )


def test_extract_path_delete_file() -> None:
    args = {"file_path": "/project/src/main.py"}
    assert _extract_path_from_tool_args("delete_file", args) == "/project/src/main.py"


def test_extract_path_unknown_tool() -> None:
    args = {"path": "/some/path"}
    assert _extract_path_from_tool_args("unknown_tool", args) == "/some/path"


def test_extract_path_no_path() -> None:
    args = {"foo": "bar"}
    assert _extract_path_from_tool_args("write_file", args) is None


def test_hook_skips_non_mutation_tools() -> None:
    cache = MagicMock(spec=ScanCache)
    # Temporarily bind global cache
    import code_muse.fs_scan_cache.invalidation_hooks as hooks

    original = hooks._cache
    hooks._cache = cache
    try:
        result = _on_post_tool_call("read_file", {"file_path": "/a.py"}, "ok", 1.0)
        _run(result)
        cache.invalidate_for_path.assert_not_called()
    finally:
        hooks._cache = original


def test_hook_invalidates_on_write_file() -> None:
    cache = MagicMock(spec=ScanCache)
    import code_muse.fs_scan_cache.invalidation_hooks as hooks

    original = hooks._cache
    hooks._cache = cache
    try:
        result = _on_post_tool_call(
            "write_file", {"file_path": "/project/src/main.py"}, "ok", 1.0
        )
        _run(result)
        cache.invalidate_for_path.assert_called_once()
        args, _ = cache.invalidate_for_path.call_args
        assert "main.py" in str(args[0])
    finally:
        hooks._cache = original


def test_hook_invalidates_parent_on_delete_file() -> None:
    cache = MagicMock(spec=ScanCache)
    import code_muse.fs_scan_cache.invalidation_hooks as hooks

    original = hooks._cache
    hooks._cache = cache
    try:
        result = _on_post_tool_call(
            "delete_file", {"file_path": "/project/src/main.py"}, "ok", 1.0
        )
        _run(result)
        cache.invalidate_for_path.assert_called_once()
        args, _ = cache.invalidate_for_path.call_args
        # Should be the parent directory, not the file itself
        assert "src" in str(args[0])
    finally:
        hooks._cache = original


def test_hook_thread_safety() -> None:
    cache = ScanCache()

    def scanner() -> Any:
        return []

    # Pre-populate cache
    cache.get_or_scan(("/project/src", False, True, True), scanner)
    cache.get_or_scan(("/project/tests", False, True, True), scanner)
    assert cache.stats.size == 2

    import code_muse.fs_scan_cache.invalidation_hooks as hooks

    original = hooks._cache
    hooks._cache = cache
    try:
        errors: list[Exception] = []

        def worker() -> None:
            try:
                result = _on_post_tool_call(
                    "write_file",
                    {"file_path": "/project/src/main.py"},
                    "ok",
                    1.0,
                )
                _run(result)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        # Only /project/src is an ancestor of /project/src/main.py;
        # /project/tests is unrelated and should remain.
        assert cache.stats.size == 1
    finally:
        hooks._cache = original


def test_register_invalidation_hooks_sets_cache() -> None:
    cache = ScanCache()
    import code_muse.fs_scan_cache.invalidation_hooks as hooks

    original = hooks._cache
    try:
        hooks._cache = None
        register_invalidation_hooks(cache)
        assert hooks._cache is cache
    finally:
        hooks._cache = original
