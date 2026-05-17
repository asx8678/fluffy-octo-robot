"""Models configuration loading with caching.

Extracted from model_factory.py.  Handles loading the bundled
``models.json``, user overlays, extra model sources (ChatGPT, Claude,
Gemini, Copilot OAuth files), and plugin models via the
``on_load_models_config`` callback.
"""

import logging
import pathlib

import orjson

from code_muse import callbacks
from code_muse._models_config_utils import (
    get_cached_config,
    models_config_fingerprint,
    set_cached_config,
)
from code_muse.config import EXTRA_MODELS_FILE, MODELS_FILE

logger = logging.getLogger(__name__)


def load_models_config() -> dict:
    """Load and cache the full models configuration.

    Sources (in merge order):
    1. Bundled ``models.json`` (or ``load_model_config`` callback)
    2. User-level ``models.json`` overlay
    3. Extra model source files (ChatGPT, Claude, Gemini, Copilot)
    4. Plugin models via ``on_load_models_config`` callback

    Results are fingerprinted and cached; re-reading only happens when
    source files change on disk.
    """
    # PERF-06: Return cached config when source files haven't changed.
    fingerprint = models_config_fingerprint()
    cached_config, cached_fp = get_cached_config()
    if cached_config is not None and cached_fp == fingerprint:
        return cached_config

    # --- Original loading logic (cache miss) ---
    load_model_config_callbacks = callbacks.get_callbacks("load_model_config")
    if len(load_model_config_callbacks) > 0:
        if len(load_model_config_callbacks) > 1:
            logging.getLogger(__name__).warning(
                "Multiple load_model_config callbacks registered, using the first"
            )
        config = callbacks.on_load_model_config()[0]
    else:
        # Always load from the bundled models.json so upstream
        # updates propagate automatically.  User additions belong
        # in extra_models.json (overlay loaded below).
        # NOTE: __file__ is in code_muse/model_factory/; go up one level
        # to reach code_muse/models.json.
        bundled_models = pathlib.Path(__file__).parent.parent / "models.json"
        with open(bundled_models) as f:
            config = orjson.loads(f.read())

    # User-level models.json overrides bundled config
    user_models = pathlib.Path(MODELS_FILE)
    if user_models.exists():
        try:
            with open(user_models) as f:
                config.update(orjson.loads(f.read()))
        except orjson.JSONDecodeError as exc:
            logging.getLogger(__name__).warning(
                f"Failed to load user models config from {user_models}: Invalid JSON - {exc}"
            )
        except Exception as exc:
            logging.getLogger(__name__).warning(
                f"Failed to load user models config from {user_models}: {exc}"
            )

    # Import OAuth model file paths from main config
    from code_muse.config import (
        CHATGPT_MODELS_FILE,
        CLAUDE_MODELS_FILE,
        COPILOT_MODELS_FILE,
        GEMINI_MODELS_FILE,
    )

    # Build list of extra model sources (user models handled above)
    extra_sources: list[tuple[pathlib.Path, str, bool]] = [
        (pathlib.Path(EXTRA_MODELS_FILE), "extra models", False),
        (pathlib.Path(CHATGPT_MODELS_FILE), "ChatGPT OAuth models", False),
        (pathlib.Path(CLAUDE_MODELS_FILE), "Claude Code OAuth models", True),
        (pathlib.Path(GEMINI_MODELS_FILE), "Gemini OAuth models", False),
        (pathlib.Path(COPILOT_MODELS_FILE), "Copilot models", False),
    ]

    for source_path, label, _use_filtered in extra_sources:
        if not source_path.exists():
            continue
        try:
            # Use filtered loading for Claude Code OAuth models to show only latest versions
            try:
                with open(source_path) as f:
                    extra_config = orjson.loads(f.read())
            except orjson.JSONDecodeError as exc:
                logging.getLogger(__name__).warning(
                    f"Failed to load {label} config from {source_path}: Invalid JSON - {exc}"
                )
                continue
            except Exception as exc:
                logging.getLogger(__name__).warning(
                    f"Failed to load {label} config from {source_path}: {exc}"
                )
                continue
            config.update(extra_config)
        except orjson.JSONDecodeError as exc:
            logging.getLogger(__name__).warning(
                f"Failed to load {label} config from {source_path}: Invalid JSON - {exc}"
            )
        except Exception as exc:
            logging.getLogger(__name__).warning(
                f"Failed to load {label} config from {source_path}: {exc}"
            )

    # Let plugins add/override models via load_models_config hook
    try:
        from code_muse.callbacks import on_load_models_config

        results = on_load_models_config()
        for result in results:
            if isinstance(result, dict):
                config.update(result)  # Plugin models override built-in
    except Exception as exc:
        logging.getLogger(__name__).debug(f"Failed to load plugin models config: {exc}")

    # --- End original loading logic ---

    # Store in cache
    set_cached_config(config, fingerprint)
    return config
