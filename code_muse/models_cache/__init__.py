"""Models Cache + LRU module for Muse.

Ports Codex's models_cache.json pattern and Oh-My-Pi's fs_cache LRU
to Python with thread-safe generics.
"""

from code_muse.models_cache.blocking_lru_cache import BlockingLruCache
from code_muse.models_cache.cache_writer import write_models_cache
from code_muse.models_cache.sha256_hash import sha256_digest, sha256_digest_file
from code_muse.models_cache.startup_integration import (
    CACHE_TTL,
    MODELS_CACHE_PATH,
    load_cached_models,
    refresh_models_cache,
)

__all__ = [
    "BlockingLruCache",
    "sha256_digest",
    "sha256_digest_file",
    "write_models_cache",
    "load_cached_models",
    "refresh_models_cache",
    "CACHE_TTL",
    "MODELS_CACHE_PATH",
]
