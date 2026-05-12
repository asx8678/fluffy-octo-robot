"""Tests for TTL policy module."""

import time

import pytest
from code_muse.fs_scan_cache.scan_cache_core import GlobMatch, ScanEntry

from code_muse.fs_scan_cache.ttl_policy import (
    CACHE_TTL_MS,
    EMPTY_RECHECK_MS,
    env_uint,
    is_fresh,
)


def test_env_uint_with_valid_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEST_UINT_VAR", "42")
    assert env_uint("TEST_UINT_VAR", 10) == 42


def test_env_uint_missing_uses_default() -> None:
    assert env_uint("TEST_UINT_VAR_NOT_SET_XYZ", 99) == 99


def test_env_uint_empty_string_uses_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEST_UINT_VAR", "")
    assert env_uint("TEST_UINT_VAR", 7) == 7


def test_env_uint_non_numeric_uses_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEST_UINT_VAR", "abc")
    assert env_uint("TEST_UINT_VAR", 7) == 7


def test_env_uint_negative_uses_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEST_UINT_VAR", "-5")
    assert env_uint("TEST_UINT_VAR", 7) == 7


def test_default_constants() -> None:
    assert CACHE_TTL_MS == 1000
    assert EMPTY_RECHECK_MS == 200


def test_is_fresh_non_empty_within_ttl() -> None:
    entry = ScanEntry(
        entries=[GlobMatch(path="/a.py", file_type="file", mtime=1.0, size=10)],
        created_at=time.monotonic() - 0.5,
    )
    assert is_fresh(entry, time.monotonic()) is True


def test_is_fresh_non_empty_past_ttl() -> None:
    entry = ScanEntry(
        entries=[GlobMatch(path="/a.py", file_type="file", mtime=1.0, size=10)],
        created_at=time.monotonic() - 2.0,
    )
    assert is_fresh(entry, time.monotonic()) is False


def test_is_fresh_empty_within_recheck() -> None:
    entry = ScanEntry(entries=[], created_at=time.monotonic() - 0.1)
    assert is_fresh(entry, time.monotonic()) is True


def test_is_fresh_empty_past_recheck() -> None:
    entry = ScanEntry(entries=[], created_at=time.monotonic() - 0.5)
    assert is_fresh(entry, time.monotonic()) is False


def test_is_fresh_ttl_zero_always_stale(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FS_SCAN_CACHE_TTL_MS", "0")
    # Force re-import of the constants by reloading the module
    import importlib

    from code_muse.fs_scan_cache import ttl_policy

    importlib.reload(ttl_policy)

    entry = ScanEntry(
        entries=[GlobMatch(path="/a.py", file_type="file", mtime=1.0, size=10)],
        created_at=time.monotonic(),
    )
    assert ttl_policy.is_fresh(entry, time.monotonic()) is False


def test_is_fresh_empty_with_ttl_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FS_SCAN_CACHE_TTL_MS", "0")
    import importlib

    from code_muse.fs_scan_cache import ttl_policy

    importlib.reload(ttl_policy)

    entry = ScanEntry(entries=[], created_at=time.monotonic())
    assert ttl_policy.is_fresh(entry, time.monotonic()) is False
