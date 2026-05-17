"""Shared utilities for model config fingerprinting and caching.

Consolidates the duplicate _models_config_fingerprint / cache / lock
implementations that previously lived in both model_factory.py and
summarization_agent.py.  A single source of truth prevents algorithm
divergence and ensures both modules see the same cache state.
"""

import hashlib
import pathlib
import threading
from typing import Any

# ---------------------------------------------------------------------------
# Module-level config cache: (config_dict, fingerprint)
# ---------------------------------------------------------------------------

_models_config_cache: tuple[dict[str, Any] | None, tuple[float, str] | None] = (
    None,
    None,
)
# FREE-THREADED: _models_config_lock guards sync-only cache access.
# All callers are sync; keep as threading.Lock.
_models_config_lock = threading.Lock()


def models_config_fingerprint() -> tuple[float, str]:
    """Compute a lightweight fingerprint of all model config source files.

    Returns (max_mtime, content_hash) — if either changes, the cached
    config is stale and must be reloaded.
    """
    source_paths: list[pathlib.Path] = []

    # Bundled models.json is always loaded
    bundled = pathlib.Path(__file__).parent / "models.json"
    source_paths.append(bundled)

    # Extra model sources (mirrors ModelFactory.load_config)
    try:
        from code_muse.config import (
            CHATGPT_MODELS_FILE,
            CLAUDE_MODELS_FILE,
            COPILOT_MODELS_FILE,
            EXTRA_MODELS_FILE,
            GEMINI_MODELS_FILE,
            MODELS_FILE,
        )

        for p in (
            MODELS_FILE,
            EXTRA_MODELS_FILE,
            CHATGPT_MODELS_FILE,
            CLAUDE_MODELS_FILE,
            GEMINI_MODELS_FILE,
            COPILOT_MODELS_FILE,
        ):
            source_paths.append(pathlib.Path(p))
    except Exception:
        pass

    max_mtime = 0.0
    hasher = hashlib.blake2b(digest_size=16)
    for sp in source_paths:
        try:
            if sp.exists():
                stat = sp.stat()
                mtime = stat.st_mtime
                if isinstance(mtime, (int, float)):
                    max_mtime = max(max_mtime, mtime)
                    hasher.update(f"{sp}:{stat.st_size}:{mtime}".encode())
                else:
                    # Mocked stat objects in tests — force cache miss
                    max_mtime = float("inf")
        except OSError:
            pass

    return max_mtime, hasher.hexdigest()


def get_cached_config() -> tuple[dict[str, Any] | None, tuple[float, str] | None]:
    """Return the current (config_dict, fingerprint) cache entry."""
    with _models_config_lock:
        return _models_config_cache


def set_cached_config(config: dict[str, Any], fingerprint: tuple[float, str]) -> None:
    """Store a config dict with its fingerprint in the shared cache."""
    global _models_config_cache
    with _models_config_lock:
        _models_config_cache = (config, fingerprint)


def invalidate_models_config_cache() -> None:
    """Force the next config load call to reload from disk.

    Call this when settings or model files are known to have changed
    (e.g. after a ``/set`` command that modifies model config).
    """
    global _models_config_cache
    with _models_config_lock:
        _models_config_cache = (None, None)
