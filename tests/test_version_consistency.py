"""Ensure pyproject.toml version matches the version recorded in uv.lock.

Prevents the drift that happened between 0.1.40 and 0.1.41.
"""

import re
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
PYPROJECT = ROOT / "pyproject.toml"
UV_LOCK = ROOT / "uv.lock"


def _get_pyproject_version() -> str:
    with open(PYPROJECT, "rb") as f:
        data = tomllib.load(f)
    return data["project"]["version"]


def _get_uv_lock_version() -> str:
    """Extract the version of the 'code-muse' package from uv.lock."""
    text = UV_LOCK.read_text(encoding="utf-8")
    # Look for the code-muse package entry
    match = re.search(
        r'name = "code-muse"\s*\n\s*version = "([^"]+)"',
        text,
        re.MULTILINE,
    )
    if not match:
        pytest.skip("code-muse not found in uv.lock (editable dev mode?)")
    return match.group(1)


def test_pyproject_and_uv_lock_versions_match():
    pyproject_ver = _get_pyproject_version()
    uv_ver = _get_uv_lock_version()

    assert pyproject_ver == uv_ver, (
        f"Version mismatch!\n"
        f"  pyproject.toml: {pyproject_ver}\n"
        f"  uv.lock:        {uv_ver}\n"
        "Run `uv lock` after changing the version in pyproject.toml."
    )
