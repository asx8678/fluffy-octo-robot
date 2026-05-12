"""Tests for cache_writer module."""

import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from code_muse.config import DATA_DIR
from code_muse.models_cache.cache_writer import write_models_cache
from code_muse.models_dev_parser import ModelInfo


def test_write_models_cache_with_explicit_models(tmp_path: Path) -> None:
    with patch("code_muse.models_cache.cache_writer.DATA_DIR", str(tmp_path)):
        models = [
            ModelInfo(
                provider_id="openai",
                model_id="gpt-4",
                name="GPT-4",
                attachment=False,
                reasoning=True,
                tool_call=True,
                temperature=True,
                structured_output=True,
                cost_input=0.03,
                cost_output=0.06,
                cost_cache_read=0.01,
                context_length=128000,
                max_output=4096,
                input_modalities=["text", "image"],
                output_modalities=["text"],
                knowledge="2023-12",
                release_date="2023-03",
                last_updated="2024-01",
                open_weights=False,
            ),
            ModelInfo(
                provider_id="anthropic",
                model_id="claude-3-sonnet",
                name="Claude 3 Sonnet",
                attachment=False,
                reasoning=False,
                tool_call=True,
                temperature=True,
                structured_output=False,
                cost_input=0.003,
                cost_output=0.015,
                cost_cache_read=0.0005,
                context_length=200000,
                max_output=4096,
                input_modalities=["text", "image"],
                output_modalities=["text"],
                knowledge="2024-02",
                release_date="2024-03",
                last_updated="2024-04",
                open_weights=False,
            ),
        ]

        result = write_models_cache(models)
        assert result is not None

        cache_path = tmp_path / "models_cache.json"
        assert cache_path.exists()

        with open(cache_path, encoding="utf-8") as f:
            cache = json.load(f)

        assert "fetched_at" in cache
        assert cache["etag"] is None
        assert cache["client_version"] is not None
        assert isinstance(cache["models"], list)
        assert len(cache["models"]) == 2

        first = cache["models"][0]
        assert first["slug"] == "openai::gpt-4"
        assert first["display_name"] == "GPT-4"
        assert first["description"] == ""
        assert first["visibility"] == "List"
        assert first["priority"] == 0
        assert first["provider_id"] == "openai"
        assert first["model_id"] == "gpt-4"
        assert first["reasoning"] is True

        second = cache["models"][1]
        assert second["slug"] == "anthropic::claude-3-sonnet"
        assert second["priority"] == 1


def test_write_models_cache_with_bundled_data(tmp_path: Path) -> None:
    with patch("code_muse.models_cache.cache_writer.DATA_DIR", str(tmp_path)):
        result = write_models_cache()
        assert result is not None

        cache_path = tmp_path / "models_cache.json"
        assert cache_path.exists()

        with open(cache_path, encoding="utf-8") as f:
            cache = json.load(f)

        assert "fetched_at" in cache
        assert isinstance(cache["models"], list)
        assert len(cache["models"]) > 0

        # Verify structure of first model
        first = cache["models"][0]
        assert "slug" in first
        assert "display_name" in first
        assert "priority" in first


def test_write_models_cache_fetched_at_is_iso() -> None:
    with patch(
        "code_muse.models_cache.cache_writer.DATA_DIR", str(tmp_path := Path(DATA_DIR))
    ) as _:
        # Use a temporary data dir to avoid side effects
        pass

    with patch("code_muse.models_cache.cache_writer.DATA_DIR", str(tmp_path)):
        write_models_cache([])
        cache_path = tmp_path / "models_cache.json"
        with open(cache_path, encoding="utf-8") as f:
            cache = json.load(f)

        fetched_at = datetime.fromisoformat(cache["fetched_at"])
        assert fetched_at.tzinfo is not None
        age = datetime.now(UTC) - fetched_at
        assert age.total_seconds() < 5


def test_write_models_cache_empty_list() -> None:
    with patch(
        "code_muse.models_cache.cache_writer.DATA_DIR", str(tmp_path := Path(DATA_DIR))
    ) as _:
        pass

    with patch("code_muse.models_cache.cache_writer.DATA_DIR", str(tmp_path)):
        result = write_models_cache([])
        assert result is not None
        cache_path = tmp_path / "models_cache.json"
        with open(cache_path, encoding="utf-8") as f:
            cache = json.load(f)
        assert cache["models"] == []


def test_write_models_cache_graceful_failure(tmp_path: Path) -> None:
    # Patch os.makedirs to raise, simulating a write failure
    with (
        patch(
            "code_muse.models_cache.cache_writer.os.makedirs",
            side_effect=OSError("no space"),
        ),
        patch("code_muse.models_cache.cache_writer.DATA_DIR", str(tmp_path)),
    ):
        result = write_models_cache([])
        assert result is None
