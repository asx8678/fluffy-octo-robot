"""Pytest configuration for security regression tests.

All tests collected under tests/security/ are automatically marked with
the ``security`` pytest marker.
"""

from pathlib import Path

import pytest

# Canonical path for detecting security test items
_SECURITY_DIR = Path(__file__).resolve().parent


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Automatically mark all tests under tests/security/ as 'security'.

    Uses item path resolution so it works across platforms (Windows, macOS, Linux).
    Idempotent: won't add a duplicate marker if one already exists.
    """
    for item in items:
        # item.path is a pathlib.Path (pytest >= 7.0); resolve for cross-platform
        # comparison with our _SECURITY_DIR reference.
        item_path = item.path.resolve()
        if _SECURITY_DIR in item_path.parents:
            has_marker = any(m.name == "security" for m in item.iter_markers())
            if not has_marker:
                item.add_marker(pytest.mark.security)
