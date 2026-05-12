"""Tests for sha256_hash utilities."""

from pathlib import Path

from code_muse.models_cache.sha256_hash import sha256_digest, sha256_digest_file


def test_sha256_digest_empty() -> None:
    result = sha256_digest(b"")
    assert len(result) == 64
    assert result == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


def test_sha256_digest_deterministic() -> None:
    data = b"hello world"
    assert sha256_digest(data) == sha256_digest(data)
    assert sha256_digest(data) != sha256_digest(b"hello world!")


def test_sha256_digest_known_value() -> None:
    # Known SHA-256 for "abc"
    assert (
        sha256_digest(b"abc")
        == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    )


def test_sha256_digest_file(tmp_path: Path) -> None:
    file_path = tmp_path / "test.txt"
    file_path.write_bytes(b"file content for hashing")
    result = sha256_digest_file(file_path)
    assert len(result) == 64
    assert result == sha256_digest(b"file content for hashing")


def test_sha256_digest_file_large(tmp_path: Path) -> None:
    file_path = tmp_path / "large.bin"
    data = b"x" * (65536 * 3 + 123)  # Multiple 64KB chunks + remainder
    file_path.write_bytes(data)
    result = sha256_digest_file(file_path)
    assert len(result) == 64
    assert result == sha256_digest(data)
