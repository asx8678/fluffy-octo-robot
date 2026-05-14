"""Write models_cache.json to the data directory.

Ports Codex's models_cache.json pattern: a snapshot of the full model
catalog bundled with the client, refreshed on startup.
"""

import dataclasses
import orjson as json
import logging
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from code_muse.config import DATA_DIR
from code_muse.models_dev_parser import (
    BUNDLED_JSON_FILENAME,
    ModelInfo,
    ModelsDevRegistry,
)

logger = logging.getLogger(__name__)


def _client_version() -> str:
    """Return the installed code-muse version."""
    try:
        from importlib.metadata import version

        return version("code-muse")
    except Exception:
        return "unknown"


def _model_to_dict(model: ModelInfo, priority: int) -> dict[str, Any]:
    """Serialize a ModelInfo into the cache entry format."""
    base = {
        "slug": model.full_id,
        "display_name": model.name,
        "description": "",
        "visibility": "List",
        "priority": priority,
    }
    # Include all dataclass fields for completeness
    fields = dataclasses.asdict(model)
    # Avoid duplicating keys we already set explicitly
    for key, value in fields.items():
        if key not in base:
            base[key] = value
    return base


def write_models_cache(models: list[ModelInfo] | None = None) -> Path | None:
    """Write the models cache file.

    Args:
        models: Optional explicit list of ModelInfo objects. If None,
            loads from the bundled models_dev_api.json.

    Returns:
        Path to the written file, or None if writing failed.
    """
    try:
        if models is None:
            bundled_path = Path(__file__).parent.parent / BUNDLED_JSON_FILENAME
            registry = ModelsDevRegistry(bundled_path)
            models = list(registry.models.values())

        cache_data: dict[str, Any] = {
            "fetched_at": datetime.now(UTC).isoformat(),
            "etag": None,
            "client_version": _client_version(),
            "models": [_model_to_dict(m, priority=idx) for idx, m in enumerate(models)],
        }

        cache_path = Path(DATA_DIR) / "models_cache.json"
        os.makedirs(cache_path.parent, exist_ok=True)
        with open(cache_path, "w", encoding="utf-8") as f:
            f.write(orjson.dumps(cache_data, option=orjson.OPT_INDENT_2, default=str).decode())

        logger.info(f"Wrote models cache ({len(models)} models) to {cache_path}")
        return cache_path

    except (OSError, ValueError, TypeError) as exc:
        logger.warning(f"Failed to write models cache: {exc}")
        return None
