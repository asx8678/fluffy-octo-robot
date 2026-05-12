# cython: language_level=3
"""SHA-256 content hash utility for content-addressed cache keys."""

import hashlib
from pathlib import Path


def sha256_digest(data: bytes) -> str:
    """Return the SHA-256 hex digests of the given bytes.

    Returns a 64-character lowercase hex string.
    """
    return hashlib.sha256(data).hexdigest()


def sha256_digest_file(path: Path) -> str:
    """Return the SHA-256 hex digests of a file's contents.

    Streams the file in 64KB chunks to handle large files efficiently.
    The chunk-reading loop uses typed locals and bound methods to avoid
    Python-level attribute lookups.
    """
    cdef object hasher = hashlib.sha256()
    cdef bytes chunk
    cdef object update = hasher.update
    cdef object read
    with open(path, "rb") as f:
        read = f.read
        while True:
            chunk = read(65536)
            if len(chunk) == 0:
                break
            update(chunk)
    return hasher.hexdigest()
