import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from code_muse.session_storage import (
    list_sessions,
    load_session,
    save_session,
)


class TestSessionStorageExtended:
    """Extended tests for session storage functionality."""

    @pytest.fixture
    def sample_history(self) -> list[Any]:
        """Sample session history for testing."""
        return [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there!"},
            {"role": "user", "content": "How are you?"},
        ]

    @pytest.fixture
    def token_estimator(self) -> Callable[[Any], int]:
        """Simple token estimator for testing."""
        return lambda message: len(str(message))

    def test_save_autosave_session(
        self,
        tmp_path: Path,
        sample_history: list[Any],
        token_estimator: Callable[[Any], int],
    ):
        """Test autosave functionality."""
        metadata = save_session(
            history=sample_history,
            session_name="autosave_test",
            base_dir=tmp_path,
            timestamp="2024-01-01T12:00:00",
            token_estimator=token_estimator,
            auto_saved=True,
        )

        assert metadata.auto_saved is True

        # Check metadata file contains auto_saved flag
        with metadata.metadata_path.open("r") as f:
            stored_data = json.load(f)
        assert stored_data["auto_saved"] is True

    def test_save_empty_session(
        self, tmp_path: Path, token_estimator: Callable[[Any], int]
    ):
        """Test saving and loading empty session."""
        metadata = save_session(
            history=[],
            session_name="empty_session",
            base_dir=tmp_path,
            timestamp="2024-01-01T12:00:00",
            token_estimator=token_estimator,
        )

        assert metadata.message_count == 0
        assert metadata.total_tokens == 0

        # Should be able to load empty history
        loaded = load_session("empty_session", tmp_path)
        assert loaded == []

    def test_overwrite_existing_session(
        self,
        tmp_path: Path,
        sample_history: list[Any],
        token_estimator: Callable[[Any], int],
    ):
        """Test overwriting an existing session."""
        # Save initial session
        save_session(
            history=["initial"],
            session_name="overwrite_test",
            base_dir=tmp_path,
            timestamp="2024-01-01T10:00:00",
            token_estimator=token_estimator,
        )

        # Overwrite with new data
        new_metadata = save_session(
            history=sample_history,
            session_name="overwrite_test",
            base_dir=tmp_path,
            timestamp="2024-01-01T12:00:00",
            token_estimator=token_estimator,
        )

        # Should load the new data
        loaded_history = load_session("overwrite_test", tmp_path)
        assert loaded_history == sample_history
        assert new_metadata.timestamp == "2024-01-01T12:00:00"

    def test_corrupted_session_file(self, tmp_path: Path):
        """Test error handling for corrupted/unsigned pickle files.

        Unsigned binary pickle files are rejected for security and raise
        FileNotFoundError (same as missing) rather than attempting to
        deserialize arbitrary data.
        """
        # Create corrupted pickle file (unsigned binary data)
        session_name = "corrupted_session"
        pickle_path = tmp_path / f"{session_name}.pkl"

        with pickle_path.open("wb") as f:
            f.write(b"not valid pickle data")

        # Should raise FileNotFoundError (security rejection of unsigned pickle)
        with pytest.raises(FileNotFoundError):
            load_session(session_name, tmp_path)

    def test_missing_session_file(self, tmp_path: Path):
        """Test error handling for missing session files."""
        # Try to load non-existent session
        with pytest.raises(FileNotFoundError):
            load_session("nonexistent_session", tmp_path)

    def test_permission_error_handling(
        self,
        tmp_path: Path,
        sample_history: list[Any],
        token_estimator: Callable[[Any], int],
    ):
        """Test handling permission errors."""
        # Create read-only directory
        readonly_dir = tmp_path / "readonly"
        readonly_dir.mkdir()
        readonly_dir.chmod(0o444)  # Read-only

        try:
            # Should fail when trying to save
            with pytest.raises((PermissionError, OSError)):
                save_session(
                    history=sample_history,
                    session_name="perm_test",
                    base_dir=readonly_dir,
                    timestamp="2024-01-01T12:00:00",
                    token_estimator=token_estimator,
                )
        finally:
            # Restore permissions for cleanup
            readonly_dir.chmod(0o755)

    def test_unicode_content(
        self, tmp_path: Path, token_estimator: Callable[[Any], int]
    ):
        """Test handling unicode and special characters."""
        unicode_history = [
            "Hello 🐕",  # Dog emoji
            "Café crème",  # Accented characters
            "Привет мир",  # Cyrillic
            "🎉 Emoji test",  # More emojis
        ]

        metadata = save_session(
            history=unicode_history,
            session_name="unicode_test",
            base_dir=tmp_path,
            timestamp="2024-01-01T12:00:00",
            token_estimator=token_estimator,
        )

        # Should load with same content
        loaded_history = load_session("unicode_test", tmp_path)
        assert loaded_history == unicode_history

        # Metadata should be properly UTF-8 encoded
        with metadata.metadata_path.open("r", encoding="utf-8") as f:
            stored_data = json.load(f)
        assert stored_data["session_name"] == "unicode_test"

    def test_complex_data_types(
        self, tmp_path: Path, token_estimator: Callable[[Any], int]
    ):
        """Test saving and loading complex data structures.

        Note: JSON serialization converts tuples to lists, so we avoid
        tuples in the test data to ensure exact round-trip equality.
        """
        complex_history = [
            {
                "role": "user",
                "content": "test",
                "metadata": {"timestamp": "2024-01-01"},
            },
            ["list", "of", "items"],
            42,
            None,
            # Tuples are serialized as lists by JSON, so we use a list here
            ["tuple", "data"],
        ]

        save_session(
            history=complex_history,
            session_name="complex_test",
            base_dir=tmp_path,
            timestamp="2024-01-01T12:00:00",
            token_estimator=token_estimator,
        )

        loaded_history = load_session("complex_test", tmp_path)
        assert loaded_history == complex_history

    def test_large_session_data(
        self, tmp_path: Path, token_estimator: Callable[[Any], int]
    ):
        """Test handling large session data."""
        large_history = [f"message_{i}" for i in range(1000)]

        metadata = save_session(
            history=large_history,
            session_name="large_test",
            base_dir=tmp_path,
            timestamp="2024-01-01T12:00:00",
            token_estimator=token_estimator,
        )

        assert metadata.message_count == 1000
        assert metadata.total_tokens > 0

        # Should be able to load large data
        loaded_history = load_session("large_test", tmp_path)
        assert loaded_history == large_history
        assert len(loaded_history) == 1000

    def test_nested_directories(
        self,
        tmp_path: Path,
        sample_history: list[Any],
        token_estimator: Callable[[Any], int],
    ):
        """Test saving to and loading from nested directories."""
        nested_dir = tmp_path / "level1" / "level2" / "sessions"

        save_session(
            history=sample_history,
            session_name="nested_session",
            base_dir=nested_dir,
            timestamp="2024-01-01T12:00:00",
            token_estimator=token_estimator,
        )

        # Directory should be created
        assert nested_dir.exists()
        assert nested_dir.is_dir()

        # Should be able to load from nested path
        loaded_history = load_session("nested_session", nested_dir)
        assert loaded_history == sample_history

    def test_session_name_variations(
        self, tmp_path: Path, token_estimator: Callable[[Any], int]
    ):
        """Test various session name formats."""
        test_cases = [
            ("simple", ["data"]),
            ("with-dashes", ["dash data"]),
            ("with_underscores", ["underscore data"]),
            ("with.dots", ["dot data"]),
            ("with spaces", ["space data"]),
        ]

        for session_name, history in test_cases:
            metadata = save_session(
                history=history,
                session_name=session_name,
                base_dir=tmp_path,
                timestamp="2024-01-01T12:00:00",
                token_estimator=token_estimator,
            )

            # Files should exist with correct names
            expected_pickle = tmp_path / f"{session_name}.pkl"
            expected_meta = tmp_path / f"{session_name}_meta.json"
            assert metadata.pickle_path == expected_pickle
            assert metadata.metadata_path == expected_meta

            # Should be able to load
            loaded_history = load_session(session_name, tmp_path)
            assert loaded_history == history

        # All should be listable
        all_sessions = list_sessions(tmp_path)
        assert len(all_sessions) == len(test_cases)
        for session_name, _ in test_cases:
            assert session_name in all_sessions
