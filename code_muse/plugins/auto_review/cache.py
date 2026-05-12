"""In-memory cache for auto-review results."""

import hashlib


class ReviewCache:
    """Simple cache keyed by SHA256(file_path + content_hash)."""

    def __init__(self) -> None:
        self._cache: dict[str, dict] = {}

    def _key(self, file_path: str, content_hash: str) -> str:
        return hashlib.sha256(f"{file_path}::{content_hash}".encode()).hexdigest()

    def get(self, file_path: str, content_hash: str) -> dict | None:
        """Return cached review result or None."""
        return self._cache.get(self._key(file_path, content_hash))

    def set(self, file_path: str, content_hash: str, result: dict) -> None:
        """Store a review result in the cache."""
        self._cache[self._key(file_path, content_hash)] = result

    def clear(self) -> None:
        """Clear all cached entries."""
        self._cache.clear()


_review_cache = ReviewCache()


def get_review_cache() -> ReviewCache:
    """Return the module-level ReviewCache singleton."""
    return _review_cache
