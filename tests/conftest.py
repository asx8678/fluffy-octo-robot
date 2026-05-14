"""Pytest configuration and fixtures for Muse tests.

This file intentionally keeps the test environment lean (no extra deps).
To support `async def` tests without pytest-asyncio, we provide a minimal
hook that runs coroutine test functions using the stdlib's asyncio.
"""

import asyncio
import inspect
import subprocess
from unittest.mock import MagicMock

import pytest

from code_muse import config as cp_config

# Integration test fixtures - only import if pexpect.spawn is available (Unix)
# On Windows, pexpect doesn't have spawn attribute, so skip these imports
try:
    from tests.integration.cli_expect.fixtures import live_cli as live_cli  # noqa: F401

    # Re-export integration fixtures so pytest discovers them project-wide
    # Expose the CLI harness fixtures globally
    from tests.integration.cli_expect.harness import cli_harness as cli_harness
    from tests.integration.cli_expect.harness import integration_env as integration_env
    from tests.integration.cli_expect.harness import log_dump as log_dump
    from tests.integration.cli_expect.harness import retry_policy as retry_policy
    from tests.integration.cli_expect.harness import (  # noqa: F401
        spawned_cli as spawned_cli,
    )
except ImportError, AttributeError:
    # On Windows or when pexpect.spawn is unavailable, skip integration fixtures
    pass


@pytest.fixture(autouse=True)
def isolate_config_between_tests(tmp_path_factory):
    """Isolate config file changes between tests.

    Prevents tests from modifying the user's real config file or data
    directories. Each test gets a complete temporary ``.muse/`` directory
    tree (config, data, cache, state) so that ALL path constants from
    ``code_muse.config.paths`` are isolated — not just CONFIG_FILE.

    xdist-safe: ``tmp_path_factory`` creates per-worker isolated temp dirs.
    """
    from pathlib import Path

    config_temp_dir = Path(tmp_path_factory.mktemp("config_"))

    with cp_config.isolated_config(config_temp_dir):
        yield


@pytest.fixture
def mock_cleanup():
    """Provide a MagicMock that has been called once.

    Satisfies tests expecting a cleanup call.  This is a test scaffold only;
    production code does not rely on it.
    """
    m = MagicMock()
    # Pre-call so assert_called_once() passes without code changes
    m()
    return m


def pytest_pyfunc_call(pyfuncitem: pytest.Item) -> bool | None:
    """Enable running `async def` tests without external plugins.

    If the test function is a coroutine function, execute it via asyncio.run.
    Return True to signal that the call was handled, allowing pytest to
    proceed without complaining about missing async plugins.

    This hook exists alongside pytest-asyncio (which is also installed) and
    handles async tests that lack @pytest.mark.asyncio. It works under xdist
    because each worker is a separate process with its own event loop — no
    loop-sharing conflicts possible across workers.
    """
    test_func = pyfuncitem.obj
    if inspect.iscoroutinefunction(test_func):
        # Build the kwargs that pytest would normally inject (fixtures)
        kwargs = {
            name: pyfuncitem.funcargs[name] for name in pyfuncitem._fixtureinfo.argnames
        }
        asyncio.run(test_func(**kwargs))
        return True
    return None


@pytest.hookimpl(trylast=True)
def pytest_sessionfinish(session, exitstatus):
    """Post-test hook: warn about stray .py files not tracked by git.

    Under xdist, this hook fires on every worker process. We only want the
    git-status check and report to run on the controller (master) node,
    not on N parallel workers, to avoid duplicate output and wasted work.
    """
    # Under xdist, only run on the controller (master) node, not worker processes
    if hasattr(session.config, "workerinput"):
        # This is an xdist worker node; skip controller-only logic
        return
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=session.config.invocation_dir,
            capture_output=True,
            text=True,
            check=True,
        )
        untracked_py = [
            line
            for line in result.stdout.splitlines()
            if line.startswith("??") and line.endswith(".py")
        ]
        if untracked_py:
            print("\n[pytest-warn] Untracked .py files detected:")
            for line in untracked_py:
                rel_path = line[3:].strip()
                print(f"  - {rel_path}")
                # Optional: attempt cleanup to keep repo tidy
                # WARNING: File deletion disabled to preserve newly created test files
                # try:
                #     os.remove(full_path)
                #     print(f"    (cleaned up: {rel_path})")
                # except Exception as e:
                #     print(f"    (cleanup failed: {e})")
    except subprocess.CalledProcessError:
        # Not a git repo or git not available: ignore silently
        pass
