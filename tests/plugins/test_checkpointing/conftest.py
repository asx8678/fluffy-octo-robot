"""Fixtures for checkpointing tests."""

import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def mock_project_root():
    with tempfile.TemporaryDirectory() as tmp:
        yield Path(tmp)
