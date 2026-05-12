"""Tests for cached glob/grep/find tool integration."""

from typing import Any

import pytest
from code_muse.fs_scan_cache.scan_cache_core import GlobMatch

from code_muse.fs_scan_cache.tool_integration import (
    cached_find,
    cached_glob,
    cached_grep,
)


def _make_temp_project(tmp_path: pytest.TempPathFactory) -> Any:
    # Helper to create a temporary project directory
    base = tmp_path.mktemp("project")
    (base / "src").mkdir()
    (base / "src" / "main.py").write_text("print('hello')\n")
    (base / "src" / "utils.py").write_text("# utils\n")
    (base / "tests").mkdir()
    (base / "tests" / "test_main.py").write_text("def test(): pass\n")
    (base / "README.md").write_text("# Project\n")
    (base / ".hidden").mkdir()
    (base / ".hidden" / "secret.py").write_text("secret\n")
    (base / "node_modules").mkdir()
    (base / "node_modules" / "pkg").mkdir()
    (base / "node_modules" / "pkg" / "index.js").write_text("module.exports = 1\n")
    return base


@pytest.fixture
def project(tmp_path_factory: pytest.TempPathFactory) -> Any:
    return _make_temp_project(tmp_path_factory)


def test_cached_glob_no_cache(project: Any) -> None:
    entries, age = cached_glob("*.py", root=str(project), cache=False)
    assert age is None
    assert isinstance(entries, list)
    # No recursion, so only files directly in project root
    assert all(str(project) in e.path for e in entries)


def test_cached_glob_with_cache(project: Any) -> None:
    # Wipe any default cache from prior tests
    import code_muse.fs_scan_cache.tool_integration as ti

    ti._default_cache = None

    entries1, age1 = cached_glob("**/*.py", root=str(project), cache=True)
    assert age1 == 0.0
    # Should find main.py, utils.py, test_main.py
    assert len(entries1) >= 3

    entries2, age2 = cached_glob("**/*.py", root=str(project), cache=True)
    assert age2 is not None
    assert age2 > 0.0
    assert [e.path for e in entries1] == [e.path for e in entries2]


def test_cached_glob_hidden_filter(project: Any) -> None:
    ti = __import__(
        "code_muse.fs_scan_cache.tool_integration", fromlist=["_default_cache"]
    )
    ti._default_cache = None

    with_hidden, _ = cached_glob("**/*.py", root=str(project), hidden=True, cache=True)
    without_hidden, _ = cached_glob(
        "**/*.py", root=str(project), hidden=False, cache=True
    )
    # hidden=True should include .hidden/secret.py
    hidden_paths = [e.path for e in with_hidden if ".hidden" in e.path]
    assert len(hidden_paths) == 1
    hidden_paths_no = [e.path for e in without_hidden if ".hidden" in e.path]
    assert len(hidden_paths_no) == 0


def test_cached_glob_node_modules_filter(project: Any) -> None:
    ti = __import__(
        "code_muse.fs_scan_cache.tool_integration", fromlist=["_default_cache"]
    )
    ti._default_cache = None

    # node_modules=True means "skip node_modules"
    skipped, _ = cached_glob(
        "**/*.js", root=str(project), node_modules=True, cache=True
    )
    # node_modules=False means "include node_modules"
    included, _ = cached_glob(
        "**/*.js", root=str(project), node_modules=False, cache=True
    )
    assert len(skipped) == 0
    assert len(included) == 1


def test_cached_grep_no_cache(project: Any) -> None:
    entries, age = cached_grep(r"def test", root=str(project), cache=False)
    assert age is None
    assert len(entries) == 1
    assert "test_main.py" in entries[0].path


def test_cached_grep_with_cache(project: Any) -> None:
    ti = __import__(
        "code_muse.fs_scan_cache.tool_integration", fromlist=["_default_cache"]
    )
    ti._default_cache = None

    entries1, age1 = cached_grep(r"def test", root=str(project), cache=True)
    assert age1 == 0.0
    assert len(entries1) == 1

    entries2, age2 = cached_grep(r"def test", root=str(project), cache=True)
    assert age2 is not None
    assert age2 > 0.0


def test_cached_find_no_cache(project: Any) -> None:
    entries, age = cached_find("main.py", root=str(project), cache=False)
    assert age is None
    assert len(entries) == 1
    assert entries[0].file_type == "file"


def test_cached_find_with_cache(project: Any) -> None:
    ti = __import__(
        "code_muse.fs_scan_cache.tool_integration", fromlist=["_default_cache"]
    )
    ti._default_cache = None

    entries1, age1 = cached_find("*.py", root=str(project), cache=True)
    assert age1 == 0.0
    assert len(entries1) >= 3

    entries2, age2 = cached_find("*.py", root=str(project), cache=True)
    assert age2 is not None
    assert age2 > 0.0
    assert len(entries1) == len(entries2)


def test_cached_glob_different_patterns_different_keys(project: Any) -> None:
    ti = __import__(
        "code_muse.fs_scan_cache.tool_integration", fromlist=["_default_cache"]
    )
    ti._default_cache = None

    py_entries, _ = cached_glob("**/*.py", root=str(project), cache=True)
    md_entries, _ = cached_glob("**/*.md", root=str(project), cache=True)
    assert len(py_entries) >= 3
    assert len(md_entries) == 1
    assert "README.md" in md_entries[0].path


def test_cached_grep_max_matches(project: Any) -> None:
    # Create many files matching same pattern
    for i in range(60):
        (project / f"file_{i}.py").write_text("match = 1\n")

    ti = __import__(
        "code_muse.fs_scan_cache.tool_integration", fromlist=["_default_cache"]
    )
    ti._default_cache = None

    entries, _ = cached_grep(r"match", root=str(project), cache=False)
    # Scanner caps at 50
    assert len(entries) == 50


def test_cached_glob_returns_glob_match_objects(project: Any) -> None:
    entries, _ = cached_glob("**/*.py", root=str(project), cache=False)
    for e in entries:
        assert isinstance(e, GlobMatch)
        assert e.file_type in {"file", "dir", "symlink"}
        assert isinstance(e.mtime, (int, float))
        assert isinstance(e.size, int)
