"""Tests for compression provenance and rehydration."""

import pytest

from code_muse.plugins.semantic_compression.provenance import (
    CompressionRecord,
    ProvenanceStore,
    create_compression_record,
    get_provenance_store,
    rehydrate,
    reset_provenance_store,
)


@pytest.fixture
def sample_text() -> str:
    return "The quick brown fox jumps over the lazy dog. " * 50


@pytest.fixture
def compressed_text() -> str:
    return "fox jumps lazy dog"  # Heavily compressed version


def test_create_and_retrieve_record(sample_text, compressed_text):
    reset_provenance_store()
    record = create_compression_record(
        original=sample_text,
        compressed=compressed_text,
        tier="tier1",
        tool_name="read_file",
    )
    assert record is not None
    assert record.original_hash
    assert record.original_size_tokens > 0
    assert record.compressed_size_tokens > 0
    assert record.tool_name == "read_file"
    assert record.compression_tier == "tier1"


def test_rehydrate_content(sample_text, compressed_text):
    reset_provenance_store()
    record = create_compression_record(
        original=sample_text,
        compressed=compressed_text,
        tier="tier1",
        tool_name="read_file",
    )

    recovered = rehydrate(record.original_hash)
    assert recovered is not None
    assert recovered == sample_text


def test_rehydrate_partial_hash(sample_text, compressed_text):
    reset_provenance_store()
    record = create_compression_record(
        original=sample_text,
        compressed=compressed_text,
        tier="tier1",
    )

    partial_hash = record.original_hash[:12]
    recovered = rehydrate(partial_hash)
    assert recovered is not None
    assert recovered == sample_text


def test_rehydrate_nonexistent():
    reset_provenance_store()
    result = rehydrate("nonexistenthash123")
    assert result is None


def test_provenance_stats(sample_text, compressed_text):
    reset_provenance_store()
    create_compression_record(
        original=sample_text,
        compressed=compressed_text,
        tier="tier1",
    )

    store = get_provenance_store()
    stats = store.get_stats()
    assert stats["count"] == 1
    assert stats["total_original_tokens"] > 0
    assert stats["compression_ratio"] < 1.0


def test_dedup_same_content(sample_text, compressed_text):
    reset_provenance_store()
    r1 = create_compression_record(
        original=sample_text,
        compressed=compressed_text,
        tier="tier1",
    )
    r2 = create_compression_record(
        original=sample_text,
        compressed=compressed_text,
        tier="tier1",
    )
    assert r1.original_hash == r2.original_hash

    store = get_provenance_store()
    stats = store.get_stats()
    assert stats["count"] == 1  # Dedup


def test_lru_eviction():
    reset_provenance_store()
    store = ProvenanceStore(max_records=2)

    # Store 3 different records
    texts = [
        ("Text one " * 100, "text one", "read_file"),
        ("Text two " * 100, "text two", "grep"),
        ("Text three " * 100, "text three", "run_shell"),
    ]

    for orig, comp, tool in texts:
        # We need to use this specific store, so create records manually
        import hashlib
        import time

        from code_muse.agents._history import estimate_tokens

        original_hash = hashlib.sha256(orig.encode("utf-8")).hexdigest()
        preview = comp[:100].replace("\n", " ")
        record = CompressionRecord(
            original_hash=original_hash,
            compressed_preview=preview,
            compression_tier="tier1",
            original_size_tokens=estimate_tokens(orig),
            compressed_size_tokens=estimate_tokens(comp),
            timestamp=time.time(),
            storage_ref="",
            tool_name=tool,
        )
        store.store_original(orig, record)

    stats = store.get_stats()
    assert stats["count"] == 2  # First should be evicted
