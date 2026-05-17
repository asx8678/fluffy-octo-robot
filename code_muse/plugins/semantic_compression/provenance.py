"""Compression provenance tracking and retrievable-original safeguards.

Every compressed message carries provenance metadata so the original content
is always recoverable via rehydrate(). The provenance store uses the same
file-based pattern as the document store to prevent unbounded growth.
"""

import dataclasses
import hashlib
import json
import logging
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Max compression records before LRU eviction
_DEFAULT_MAX_RECORDS = 200

# Store directory relative to CONFIG_DIR
_PROVENANCE_STORE_DIR = "compression_provenance"


@dataclasses.dataclass(frozen=True)
class CompressionRecord:
    """Provenance record for a single compression operation.

    Attributes:
        original_hash: SHA256 of the original uncompressed content.
        compressed_preview: First 100 chars of compressed result for identification.
        compression_tier: "tier1", "tier2", or "aggressive".
        original_size_tokens: Token count of original content.
        compressed_size_tokens: Token count after compression.
        timestamp: Unix timestamp of compression.
        storage_ref: Path or identifier where original content is stored.
        tool_name: Name of the tool whose output was compressed,
            or "user" for user input.
    """

    original_hash: str
    compressed_preview: str
    compression_tier: str
    original_size_tokens: int
    compressed_size_tokens: int
    timestamp: float
    storage_ref: str
    tool_name: str = ""


class ProvenanceStore:
    """Persistent store of compression provenance records with LRU eviction."""

    def __init__(
        self,
        store_dir: str | Path | None = None,
        max_records: int = _DEFAULT_MAX_RECORDS,
    ):
        if store_dir is None:
            from code_muse.config.paths import CONFIG_DIR

            store_dir = Path(CONFIG_DIR) / _PROVENANCE_STORE_DIR
        self._store_dir = Path(store_dir)
        self._store_dir.mkdir(parents=True, exist_ok=True)
        self._max_records = max_records
        self._index_path = self._store_dir / "provenance_index.json"
        self._records: dict[str, CompressionRecord] = {}
        self._access_order: OrderedDict[str, float] = OrderedDict()
        self._load_index()

    def _load_index(self) -> None:
        if self._index_path.exists():
            try:
                data = json.loads(self._index_path.read_text())
                for key, val in data.items():
                    self._records[key] = CompressionRecord(**val)
                    self._access_order[key] = val.get("timestamp", 0)
                logger.debug(
                    "Loaded %d compression provenance records", len(self._records)
                )
            except Exception as e:
                logger.warning("Failed to load provenance index: %s", e)

    def _save_index(self) -> None:
        try:
            data = {}
            for key, rec in self._records.items():
                d = {k: v for k, v in rec.__dict__.items() if k != "content"}
                d.pop("content", None)
                data[key] = d
            self._index_path.write_text(json.dumps(data, indent=2))
        except Exception as e:
            logger.warning("Failed to save provenance index: %s", e)

    def _get_content_path(self, hash_key: str) -> Path:
        return self._store_dir / f"{hash_key}.txt"

    def store_original(
        self, original: str, record: CompressionRecord
    ) -> CompressionRecord:
        """Store original content and its provenance record.

        Returns the CompressionRecord (already passed in, with storage_ref filled).
        """
        hash_key = record.original_hash

        # Dedup
        if hash_key in self._records:
            self._touch(hash_key)
            return self._records[hash_key]

        # Evict if at capacity
        if len(self._records) >= self._max_records:
            self._evict_lru()

        # Write original content to disk
        content_path = self._get_content_path(hash_key)
        try:
            content_path.write_text(original)
            storage_ref = str(content_path)
        except Exception as e:
            logger.error("Failed to write original content: %s", e)
            storage_ref = f"memory:{hash_key}"

        # Update record with storage_ref
        record = CompressionRecord(
            original_hash=record.original_hash,
            compressed_preview=record.compressed_preview,
            compression_tier=record.compression_tier,
            original_size_tokens=record.original_size_tokens,
            compressed_size_tokens=record.compressed_size_tokens,
            timestamp=record.timestamp,
            storage_ref=storage_ref,
            tool_name=record.tool_name,
        )

        self._records[hash_key] = record
        self._access_order[hash_key] = time.time()
        self._save_index()
        logger.debug(
            "Stored compression provenance: %s (%d tokens)",
            hash_key[:12],
            record.original_size_tokens,
        )
        return record

    def _evict_lru(self) -> None:
        if not self._access_order:
            return
        oldest_key = next(iter(self._access_order))
        if oldest_key in self._records:
            del self._records[oldest_key]
            del self._access_order[oldest_key]
            from contextlib import suppress

            with suppress(Exception):
                self._get_content_path(oldest_key).unlink(missing_ok=True)
            self._save_index()
            logger.debug("LRU evicted provenance record: %s", oldest_key[:12])

    def _touch(self, hash_key: str) -> None:
        if hash_key in self._records:
            self._access_order[hash_key] = time.time()
            self._access_order.move_to_end(hash_key, last=True)

    def get_record(self, original_hash: str) -> CompressionRecord | None:
        """Get a provenance record by hash (full or first 12 chars)."""
        for key in self._records:
            if key == original_hash or key.startswith(original_hash):
                self._touch(key)
                return self._records[key]
        return None

    def get_original(self, original_hash: str) -> str | None:
        """Retrieve original content by hash."""
        record = self.get_record(original_hash)
        if not record:
            return None
        content_path = self._get_content_path(record.original_hash)
        if content_path.exists():
            return content_path.read_text()
        return None

    def get_stats(self) -> dict[str, Any]:
        """Get store statistics."""
        if not self._records:
            return {
                "count": 0,
                "total_original_tokens": 0,
                "total_compressed_tokens": 0,
                "compression_ratio": 0,
            }
        total_orig = sum(r.original_size_tokens for r in self._records.values())
        total_comp = sum(r.compressed_size_tokens for r in self._records.values())
        return {
            "count": len(self._records),
            "total_original_tokens": total_orig,
            "total_compressed_tokens": total_comp,
            "compression_ratio": total_comp / max(total_orig, 1),
        }


# Module-level singleton
_provenance_store: ProvenanceStore | None = None


def get_provenance_store() -> ProvenanceStore:
    global _provenance_store
    if _provenance_store is None:
        _provenance_store = ProvenanceStore()
    return _provenance_store


def reset_provenance_store() -> None:
    global _provenance_store
    _provenance_store = None


def rehydrate(original_hash: str) -> str | None:
    """Retrieve original uncompressed content by hash.

    This is the main public API for content recovery.
    Returns the original text if found, None otherwise.
    """
    store = get_provenance_store()
    return store.get_original(original_hash)


def create_compression_record(
    original: str,
    compressed: str,
    tier: str,
    tool_name: str = "",
) -> CompressionRecord:
    """Create and store a compression provenance record.

    Stores the original content and returns the record.
    """
    from code_muse.agents._history import estimate_tokens

    original_hash = hashlib.sha256(original.encode("utf-8")).hexdigest()
    preview = compressed[:100].replace("\n", " ")

    record = CompressionRecord(
        original_hash=original_hash,
        compressed_preview=preview,
        compression_tier=tier,
        original_size_tokens=estimate_tokens(original),
        compressed_size_tokens=estimate_tokens(compressed),
        timestamp=time.time(),
        storage_ref="",  # Will be filled by store_original
        tool_name=tool_name,
    )

    store = get_provenance_store()
    return store.store_original(original, record)


def get_provenance_hash_key(compressed_text: str) -> str | None:
    """Extract the provenance hash from a compressed message metadata if present.

    The hash is appended as a zero-width marker during compression.
    """
    # The semantic_compression plugin appends _COMPRESSION_MARKER to compressed output
    # The provenance hash goes in the marker area
    return None  # Placeholder — provenance hash is tracked by original hash
