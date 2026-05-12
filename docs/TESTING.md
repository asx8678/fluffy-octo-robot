# Testing Guide

## Quick Reference

| What | Command |
|------|---------|
| Fast local unit loop | `uv run pytest tests/ --ignore tests/integration --ignore tests/security -m "not slow" -q --no-cov -n auto --dist loadfile` |
| Security tests | `uv run pytest tests/security/ -q --no-cov` |
| Coverage report | `uv run pytest tests/ --ignore tests/integration --ignore tests/security -m "not slow" -q --cov=code_muse --cov-report=term-missing` |
| Slowest tests | `uv run pytest tests/ --ignore tests/integration --ignore tests/security -m "not slow" -q --no-cov --durations=20` |
| Integration tests | `CI=1 MUSE_TEST_FAST=1 uv run pytest tests/integration/ -q --no-cov` |
| Everything (unit + security, no slow) | `uv run pytest tests/ --ignore tests/integration -m "not slow" -q --no-cov -n auto --dist loadfile` |

## Pytest Markers

Tests are automatically marked based on their directory:

| Marker | Description | Typical use |
|--------|-------------|-------------|
| `integration` | Integration tests (live services, CLI harness) | Skipped in PR CI and nightly; run manually or in a dedicated live-services environment |
| `security` | Security regression tests | Run in both PR CI and nightly |
| `slow` | Slow tests reserved for nightly or explicit runs | Excluded from PR CI via `-m "not slow"` |
| `serial` | Tests that cannot safely run with pytest-xdist | Excluded from `-n auto` runs (use `pytest -m serial` for serial-only) |

### Running by marker

```bash
# Skip integration tests explicitly (they're already ignored via --ignore)
uv run pytest -m "not integration" -q --no-cov

# Run only security tests
uv run pytest -m security -q --no-cov

# Run everything except slow tests (mirrors PR CI behavior)
uv run pytest -m "not slow" -q --no-cov -n auto --dist loadfile

# Run only slow tests (reserved for nightly / explicit runs)
uv run pytest -m slow -q --no-cov

# Combine markers: unit + security, excluding slow and integration
uv run pytest -m "not slow and not integration" -q --no-cov -n auto --dist loadfile
```

### Auto-marking

- Tests under `tests/integration/` are automatically marked `integration` via `conftest.py`.
- Tests under `tests/security/` are automatically marked `security` via `conftest.py`.
- No per-file or per-test `@pytest.mark.*` decorators needed for folder-level markers.

## CI Shape

### PR Checks (`ci.yml`)

Runs on every pull request:

| Job | OS | Python | What |
|-----|----|--------|------|
| Lint | ubuntu-latest | 3.13 | ruff check + format |
| Unit | ubuntu-latest | 3.11 | security + unit tests (`-m "not slow" -n auto --dist loadfile`) |
| Unit | ubuntu-latest | 3.12 | security + unit tests (`-m "not slow" -n auto --dist loadfile`) |
| Unit | ubuntu-latest | 3.13 | security + unit tests (`-m "not slow" -n auto --dist loadfile`) |
| Unit | macos-latest | 3.13 | security + unit tests (`-m "not slow" -n auto --dist loadfile`) |
| Unit | windows-latest | 3.13 | security + unit tests (`-m "not slow" -n auto --dist loadfile`) |
| Coverage | ubuntu-latest | 3.13 | unit tests with `--cov` (serial, no xdist) |

- **Excluded from PR CI**: integration tests (require live services / PTY harness), slow tests (reserved for nightly)
- **Coverage runs serially**: pytest-cov collection across xdist workers can be unreliable, so the Coverage job omits `-n auto`
- **Env**: `CI=1`, `MUSE_TEST_FAST=1`, fake API keys

### Nightly Full Matrix (`nightly.yml`)

Runs daily at 03:00 UTC and on `workflow_dispatch`:

| OS | Python versions |
|----|----------------|
| ubuntu-latest | 3.11, 3.12, 3.13 |
| macos-latest | 3.11, 3.12, 3.13 |
| windows-latest | 3.11, 3.12, 3.13 |

- Runs security tests + unit tests (including `@pytest.mark.slow` tests) across the full 3×3 matrix with `-n auto --dist loadfile`.
- Integration tests remain excluded (some require live LLM services,
  or pexpect/PTY behavior that is environment-dependent). Run integration tests
  manually or in a dedicated live-services environment.

## Environment Variables

| Variable | Purpose | Required for |
|----------|---------|-------------|
| `CI=1` | Disables Rich Live() display | Integration tests |
| `MUSE_TEST_FAST=1` | Lean/fast CLI mode | Integration tests |
| `UV_NO_MANAGED_PYTHON=1` | Use system Python | All CI |
