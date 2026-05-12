"""Startup cache integration — load cached models on session start."""

import json
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from code_muse.config import MODELS_CACHE_FILE
from code_muse.models_cache.cache_writer import write_models_cache

logger = logging.getLogger(__name__)

MODELS_CACHE_PATH = Path(MODELS_CACHE_FILE)
CACHE_TTL = timedelta(hours=24)


def load_cached_models() -> list[dict[str, Any]] | None:
    """Load models from cache if fresh (< 24h old).

    Returns:
        List of model dicts if cache is fresh, None if stale or missing.
        Never raises — logs errors and returns None.
    """
    try:
        if not MODELS_CACHE_PATH.exists():
            logger.debug("models_cache.json not found")
            return None

        with open(MODELS_CACHE_PATH, encoding="utf-8") as f:
            cache = json.load(f)

        fetched_at_str = cache.get("fetched_at")
        if not fetched_at_str:
            logger.warning("models_cache.json missing fetched_at")
            return None

        fetched_at = datetime.fromisoformat(fetched_at_str)
        age = datetime.now(UTC) - fetched_at

        if age > CACHE_TTL:
            logger.debug(f"models_cache.json is {age} old, needs refresh")
            return None

        models = cache.get("models")
        if not isinstance(models, list):
            logger.warning("models_cache.json models is not a list")
            return None

        logger.info(f"Using cached models ({len(models)} models, {age} old)")
        return models

    except (OSError, ValueError) as exc:
        logger.warning(f"Failed to load models_cache.json: {exc}")
        return None


def refresh_models_cache() -> list[dict[str, Any]]:
    """Fetch fresh models and update cache.

    Returns:
        Fresh list of model dicts.
    """
    write_models_cache()
    cached = load_cached_models()
    if cached is not None:
        return cached
    # If cache write failed, load from bundled as ultimate fallback
    from code_muse.models_dev_parser import ModelsDevRegistry

    bundled_path = Path(__file__).parent.parent / "models_dev_api.json"
    registry = ModelsDevRegistry(bundled_path)
    return [
        {"slug": m.full_id, "display_name": m.name} for m in registry.models.values()
    ]
