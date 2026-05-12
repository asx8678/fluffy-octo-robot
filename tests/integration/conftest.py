"""Pytest configuration for integration tests.

Integration tests require specific environment variables to be set to prevent
hanging issues with Rich's Live() display in pexpect PTY environments.

All tests collected under tests/integration/ are automatically marked with
the ``integration`` pytest marker.
"""

import os
from pathlib import Path

import pytest

# Canonical path for detecting integration test items
_INTEGRATION_DIR = Path(__file__).resolve().parent

# Required environment variables for integration tests
REQUIRED_ENV_VARS = {
    "CI": "Disables Rich Live() display in streaming handler",
    "MUSE_TEST_FAST": "Puts CLI in fast/lean mode for testing",
}


def _check_integration_env_vars() -> tuple[bool, list[tuple[str, str]]]:
    """Check if required environment variables are set.

    Returns:
        Tuple of (all_set, missing_vars) where missing_vars is a list of
        (var_name, description) tuples.
    """
    missing_vars = []
    for var, description in REQUIRED_ENV_VARS.items():
        value = os.environ.get(var, "").lower()
        if value not in ("1", "true", "yes"):
            missing_vars.append((var, description))
    return len(missing_vars) == 0, missing_vars


def _format_skip_reason(missing_vars: list[tuple[str, str]]) -> str:
    """Format a skip reason message for missing env vars."""
    var_list = ", ".join(var for var, _ in missing_vars)
    return (
        f"Integration tests require env vars: {var_list}. "
        f"Run with: CI=1 MUSE_TEST_FAST=1 uv run pytest tests/integration/"
    )


# Check once at module load time
_ENV_VARS_OK, _MISSING_VARS = _check_integration_env_vars()
_SKIP_REASON = _format_skip_reason(_MISSING_VARS) if _MISSING_VARS else ""


@pytest.fixture(autouse=True, scope="function")
def _require_integration_env_vars():
    """Skip integration tests if required environment variables are not set.

    This fixture runs automatically for every test in the integration directory.
    It gracefully skips tests instead of bombing the entire test suite.
    """
    if not _ENV_VARS_OK:
        pytest.skip(_SKIP_REASON)


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Automatically mark all tests under tests/integration/ as 'integration'.

    Uses item path resolution so it works across platforms (Windows, macOS, Linux).
    Idempotent: won't add a duplicate marker if one already exists.
    """
    for item in items:
        # item.path is a pathlib.Path (pytest >= 7.0); resolve for cross-platform
        # comparison with our _INTEGRATION_DIR reference.
        item_path = item.path.resolve()
        if _INTEGRATION_DIR in item_path.parents:
            has_marker = any(m.name == "integration" for m in item.iter_markers())
            if not has_marker:
                item.add_marker(pytest.mark.integration)
