"""Tests for startup_integration module."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import patch

from code_muse.models_cache.startup_integration import (
    CACHE_TTL,
    load_cached_models,
    refresh_models_cache,
)


def _write_cache(
    path: Path, fetched_at: datetime | None, models: list[dict[str, Any]] | None = None
) -> None:
    cache: dict[str, Any] = {
        "fetched_at": fetched_at.isoformat() if fetched_at else None,
        "etag": None,
        "client_version": "0.6.0",
        "models": models
        if models is not None
        else [{"slug": "test::model", "display_name": "Test Model"}],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cache, f)


def test_load_cached_models_fresh_cache(tmp_path: Path) -> None:
    cache_path = tmp_path / "models_cache.json"
    fetched_at = datetime.now(UTC) - timedelta(hours=1)
    _write_cache(cache_path, fetched_at)

    with patch(
        "code_muse.models_cache.startup_integration.MODELS_CACHE_PATH", cache_path
    ):
        result = load_cached_models()

    assert result is not None
    assert isinstance(result, list)
    assert len(result) == 1
    assert result[0]["slug"] == "test::model"


def test_load_cached_models_missing_cache(tmp_path: Path) -> None:
    cache_path = tmp_path / "models_cache.json"
    with patch(
        "code_muse.models_cache.startup_integration.MODELS_CACHE_PATH", cache_path
    ):
        result = load_cached_models()
    assert result is None


def test_load_cached_models_stale_cache(tmp_path: Path) -> None:
    cache_path = tmp_path / "models_cache.json"
    fetched_at = datetime.now(UTC) - CACHE_TTL - timedelta(minutes=1)
    _write_cache(cache_path, fetched_at)

    with patch(
        "code_muse.models_cache.startup_integration.MODELS_CACHE_PATH", cache_path
    ):
        result = load_cached_models()
    assert result is None


def test_load_cached_models_missing_fetched_at(tmp_path: Path) -> None:
    cache_path = tmp_path / "models_cache.json"
    _write_cache(cache_path, None)

    with patch(
        "code_muse.models_cache.startup_integration.MODELS_CACHE_PATH", cache_path
    ):
        result = load_cached_models()
    assert result is None


def test_load_cached_models_models_not_list(tmp_path: Path) -> None:
    cache_path = tmp_path / "models_cache.json"
    fetched_at = datetime.now(UTC) - timedelta(hours=1)
    cache = {
        "fetched_at": fetched_at.isoformat(),
        "etag": None,
        "client_version": "0.6.0",
        "models": "not_a_list",
    }
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(cache, f)

    with patch(
        "code_muse.models_cache.startup_integration.MODELS_CACHE_PATH", cache_path
    ):
        result = load_cached_models()
    assert result is None


def test_load_cached_models_invalid_json(tmp_path: Path) -> None:
    cache_path = tmp_path / "models_cache.json"
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text("not json", encoding="utf-8")

    with patch(
        "code_muse.models_cache.startup_integration.MODELS_CACHE_PATH", cache_path
    ):
        result = load_cached_models()
    assert result is None


def test_refresh_models_cache(tmp_path: Path) -> None:
    cache_path = tmp_path / "models_cache.json"

    with (
        patch(
            "code_muse.models_cache.startup_integration.MODELS_CACHE_PATH", cache_path
        ),
        patch("code_muse.models_cache.cache_writer.DATA_DIR", str(tmp_path)),
    ):
        result = refresh_models_cache()

    assert result is not None
    assert isinstance(result, list)
    assert len(result) > 0
    assert "slug" in result[0]
    assert "display_name" in result[0]
    assert cache_path.exists()
