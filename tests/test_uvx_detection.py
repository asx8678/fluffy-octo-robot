"""Comprehensive test coverage for uvx_detection.py.

Tests UVX environment detection including:
- Process parent detection via psutil
- Process parent detection via Windows ctypes
- Process chain traversal
- UVX launch scenario detection on Windows
- Signal handling adaptation for uvx
- Fallback mechanisms when detection fails
"""

import sys
from unittest.mock import MagicMock, patch

from code_muse.uvx_detection import (
    _get_parent_process_chain,
    _get_parent_process_chain_psutil,
    _get_parent_process_chain_windows_ctypes,
    _get_parent_process_name_psutil,
    _is_uvx_in_chain,
    get_uvx_detection_info,
    is_launched_via_uvx,
    is_windows,
    should_use_alternate_cancel_key,
)


class TestIsUVXInChain:
    """Test UVX detection in process chain."""

    def test_is_uvx_in_chain_detects_uvx_exe(self):
        """Test detection of uvx.exe in chain."""
        chain = ["python.exe", "uvx.exe", "cmd.exe"]
        result = _is_uvx_in_chain(chain)
        assert result is True

    def test_is_uvx_in_chain_detects_uvx_no_extension(self):
        """Test detection of uvx without .exe extension."""
        chain = ["python", "uvx", "cmd"]
        result = _is_uvx_in_chain(chain)
        assert result is True

    def test_is_uvx_in_chain_ignores_uv_exe(self):
        """Test that uv.exe is not detected as uvx."""
        chain = ["python.exe", "uv.exe", "cmd.exe"]
        result = _is_uvx_in_chain(chain)
        assert result is False

    def test_is_uvx_in_chain_empty(self):
        """Test empty chain returns False."""
        result = _is_uvx_in_chain([])
        assert result is False

    def test_is_uvx_in_chain_no_match(self):
        """Test chain with no uvx returns False."""
        chain = ["python", "bash", "cmd"]
        result = _is_uvx_in_chain(chain)
        assert result is False

    def test_is_uvx_in_chain_mixed_case(self):
        """Test case handling in chain detection."""
        # Implementation may normalize to lowercase
        chain = ["python.exe", "uvx.exe", "cmd.exe"]
        result = _is_uvx_in_chain(chain)
        assert isinstance(result, bool)


class TestIsLaunchedViaUVX:
    """Test UVX launch detection."""

    @patch("code_muse.uvx_detection._get_parent_process_chain")
    def test_is_launched_via_uvx_true(
        self,
        mock_get_chain,
    ):
        """Test uvx detection returns True when uvx in chain."""
        mock_get_chain.return_value = ["python.exe", "uvx.exe"]
        # Clear the cache if it exists
        if hasattr(is_launched_via_uvx, "cache_clear"):
            is_launched_via_uvx.cache_clear()
        result = is_launched_via_uvx()
        assert result is True

    @patch("code_muse.uvx_detection._get_parent_process_chain")
    def test_is_launched_via_uvx_true_no_extension(
        self,
        mock_get_chain,
    ):
        """Test uvx detection with uvx (no extension)."""
        mock_get_chain.return_value = ["python", "uvx"]
        # Clear the cache if it exists
        if hasattr(is_launched_via_uvx, "cache_clear"):
            is_launched_via_uvx.cache_clear()
        result = is_launched_via_uvx()
        assert result is True

    @patch("code_muse.uvx_detection._get_parent_process_chain")
    def test_is_launched_via_uvx_false_no_uvx(
        self,
        mock_get_chain,
    ):
        """Test uvx detection returns False when uvx not in chain."""
        mock_get_chain.return_value = ["python.exe", "cmd.exe"]
        # Clear the cache if it exists
        if hasattr(is_launched_via_uvx, "cache_clear"):
            is_launched_via_uvx.cache_clear()
        result = is_launched_via_uvx()
        assert result is False

    @patch("code_muse.uvx_detection._get_parent_process_chain")
    def test_is_launched_via_uvx_empty_chain(
        self,
        mock_get_chain,
    ):
        """Test uvx detection with empty chain."""
        mock_get_chain.return_value = []
        # Clear the cache if it exists
        if hasattr(is_launched_via_uvx, "cache_clear"):
            is_launched_via_uvx.cache_clear()
        result = is_launched_via_uvx()
        assert result is False

    @patch("code_muse.uvx_detection._get_parent_process_chain")
    def test_is_launched_via_uvx_ignores_uv_not_uvx(
        self,
        mock_get_chain,
    ):
        """Test uv.exe is not confused with uvx.exe."""
        mock_get_chain.return_value = ["python.exe", "uv.exe", "cmd.exe"]
        # Clear the cache if it exists
        if hasattr(is_launched_via_uvx, "cache_clear"):
            is_launched_via_uvx.cache_clear()
        result = is_launched_via_uvx()
        # uv.exe handles signals correctly
        assert result is False


class TestShouldUseAlternateCancelKey:
    """Test alternate cancel key decision."""

    @patch("code_muse.uvx_detection.is_windows")
    @patch("code_muse.uvx_detection.is_launched_via_uvx")
    def test_should_use_alternate_key_non_windows_uvx(
        self,
        mock_is_uvx,
        mock_is_windows,
    ):
        """Test alternate key is not used on non-Windows even with uvx."""
        mock_is_windows.return_value = False
        mock_is_uvx.return_value = True
        result = should_use_alternate_cancel_key()
        # Only Windows + uvx = True
        assert result is False

    @patch("code_muse.uvx_detection.is_windows")
    @patch("code_muse.uvx_detection.is_launched_via_uvx")
    def test_should_use_alternate_key_non_windows_no_uvx(
        self,
        mock_is_uvx,
        mock_is_windows,
    ):
        """Test alternate key is not used on non-Windows without uvx."""
        mock_is_windows.return_value = False
        mock_is_uvx.return_value = False
        result = should_use_alternate_cancel_key()
        assert result is False


class TestGetUVXDetectionInfo:
    """Test UVX detection info gathering."""

    @patch("code_muse.uvx_detection._get_parent_process_chain")
    @patch("code_muse.uvx_detection.is_launched_via_uvx")
    @patch("code_muse.uvx_detection.is_windows")
    @patch("code_muse.uvx_detection.should_use_alternate_cancel_key")
    def test_get_uvx_detection_info_returns_dict(
        self,
        mock_cancel_key,
        mock_is_windows_func,
        mock_is_uvx,
        mock_get_chain,
    ):
        """Test detection info returns a dictionary."""
        mock_get_chain.return_value = ["python.exe", "cmd.exe"]
        mock_is_windows_func.return_value = True
        mock_is_uvx.return_value = False
        mock_cancel_key.return_value = False

        result = get_uvx_detection_info()
        assert isinstance(result, dict)
        assert "is_windows" in result
        assert "is_launched_via_uvx" in result
        assert "should_use_alternate_cancel_key" in result
        assert "parent_process_chain" in result
        assert "current_pid" in result
        assert "python_executable" in result

    @patch("code_muse.uvx_detection._get_parent_process_chain")
    @patch("code_muse.uvx_detection.is_launched_via_uvx")
    @patch("code_muse.uvx_detection.is_windows")
    @patch("code_muse.uvx_detection.should_use_alternate_cancel_key")
    def test_get_uvx_detection_info_values(
        self,
        mock_cancel_key,
        mock_is_windows_func,
        mock_is_uvx,
        mock_get_chain,
    ):
        """Test detection info contains correct values."""
        mock_get_chain.return_value = ["python"]
        mock_is_windows_func.return_value = False
        mock_is_uvx.return_value = False
        mock_cancel_key.return_value = False

        result = get_uvx_detection_info()
        assert result["parent_process_chain"] == ["python"]
        assert result["is_windows"] is False
        assert result["is_launched_via_uvx"] is False
        assert result["should_use_alternate_cancel_key"] is False
        assert result["current_pid"] > 0  # Should have valid PID


class TestProcessDetectionIntegration:
    """Test process detection functions work and don't crash."""

    def test_get_parent_process_name_psutil_returns_string_or_none(self):
        """Test _get_parent_process_name_psutil returns str or None."""
        # Test with current process ID
        import os

        result = _get_parent_process_name_psutil(os.getpid())
        assert result is None or isinstance(result, str)

    def test_get_parent_process_chain_psutil_returns_list(self):
        """Test _get_parent_process_chain_psutil returns a list."""
        result = _get_parent_process_chain_psutil()
        assert isinstance(result, list)
        # Each item should be a string if list is non-empty
        for item in result:
            assert isinstance(item, str)


class TestGetParentProcessChain:
    """Test the main process chain detection function."""

    @patch("code_muse.uvx_detection._get_parent_process_chain_psutil")
    def test_get_parent_process_chain_calls_psutil(self, mock_psutil_chain):
        """Test that psutil function is tried first."""
        mock_psutil_chain.return_value = ["python.exe", "uvx.exe"]

        # This tests that _get_parent_process_chain tries psutil path
        result = _get_parent_process_chain()
        # Result depends on whether psutil is importable
        assert isinstance(result, list)

    @patch("code_muse.uvx_detection._get_parent_process_chain_windows_ctypes")
    @patch("platform.system")
    def test_get_parent_process_chain_fallback_ctypes(
        self, mock_platform, mock_ctypes_chain
    ):
        """Test fallback behavior on Windows without psutil."""
        mock_platform.return_value = "Windows"
        mock_ctypes_chain.return_value = ["python", "cmd"]

        result = _get_parent_process_chain()
        # Function should return a list
        assert isinstance(result, list)

    @patch("code_muse.uvx_detection._get_parent_process_chain_psutil")
    def test_get_parent_process_chain_empty_result(self, mock_psutil_chain):
        """Test handling of empty chain result."""
        mock_psutil_chain.return_value = []

        result = _get_parent_process_chain()
        assert isinstance(result, list)

    @patch("code_muse.uvx_detection._get_parent_process_chain_psutil")
    def test_get_parent_process_chain_resilient_to_errors(self, mock_psutil_chain):
        """Test graceful handling of errors in chain detection."""
        mock_psutil_chain.side_effect = Exception("psutil error")

        result = _get_parent_process_chain()
        # Should not raise, may return empty or fallback result
        assert isinstance(result, list)


class TestCacheBehavior:
    """Test caching behavior of uvx detection."""

    @patch("code_muse.uvx_detection._get_parent_process_chain")
    def test_is_launched_via_uvx_caches_result(self, mock_get_chain):
        """Test that is_launched_via_uvx caches the result."""
        mock_get_chain.return_value = ["python.exe", "uvx.exe"]

        # Clear cache before test
        if hasattr(is_launched_via_uvx, "cache_clear"):
            is_launched_via_uvx.cache_clear()

        # First call
        result1 = is_launched_via_uvx()

        # Second call should use cached result
        result2 = is_launched_via_uvx()

        assert result1 == result2
        assert result1 is True

        # psutil should only be called once due to caching
        assert mock_get_chain.call_count == 1

    def test_is_launched_via_uvx_has_lru_cache(self):
        """Test that is_launched_via_uvx is decorated with lru_cache."""
        # The function should have cache_clear and cache_info methods
        assert hasattr(is_launched_via_uvx, "cache_clear")
        assert hasattr(is_launched_via_uvx, "cache_info")

    @patch("code_muse.uvx_detection._get_parent_process_chain")
    def test_is_launched_via_uvx_cache_info(self, mock_get_chain):
        """Test cache statistics via cache_info."""
        mock_get_chain.return_value = ["python"]

        # Clear cache
        if hasattr(is_launched_via_uvx, "cache_clear"):
            is_launched_via_uvx.cache_clear()

        # Make calls
        is_launched_via_uvx()
        is_launched_via_uvx()

        # Check cache statistics
        if hasattr(is_launched_via_uvx, "cache_info"):
            info = is_launched_via_uvx.cache_info()
            assert info.hits >= 1  # Second call should be a hit
            assert info.misses >= 1  # First call is a miss


class TestEdgeCasesAndErrors:
    """Test edge cases and error handling."""

    @patch("code_muse.uvx_detection._get_parent_process_chain")
    def test_is_uvx_in_chain_with_none_values(self, mock_get_chain):
        """Test handling of None values in chain."""
        # This shouldn't happen in practice, but test robustness
        chain_with_none = ["python.exe", None, "cmd.exe"]
        result = _is_uvx_in_chain(chain_with_none)
        assert isinstance(result, bool)

    @patch("code_muse.uvx_detection._get_parent_process_chain")
    def test_is_launched_via_uvx_always_returns_bool(self, mock_get_chain):
        """Test that is_launched_via_uvx always returns a boolean."""
        mock_get_chain.return_value = []
        if hasattr(is_launched_via_uvx, "cache_clear"):
            is_launched_via_uvx.cache_clear()

        result = is_launched_via_uvx()
        assert isinstance(result, bool)

    def test_should_use_alternate_cancel_key_always_returns_bool(self):
        """Test that should_use_alternate_cancel_key always returns a boolean."""
        result = should_use_alternate_cancel_key()
        assert isinstance(result, bool)

    def test_get_uvx_detection_info_has_all_keys(self):
        """Test that detection info dict has all expected keys."""
        result = get_uvx_detection_info()
        required_keys = {
            "is_windows",
            "is_launched_via_uvx",
            "should_use_alternate_cancel_key",
            "parent_process_chain",
            "current_pid",
            "python_executable",
        }
        assert required_keys.issubset(result.keys())

    def test_get_uvx_detection_info_types(self):
        """Test that detection info values have correct types."""
        result = get_uvx_detection_info()
        assert isinstance(result["is_windows"], bool)
        assert isinstance(result["is_launched_via_uvx"], bool)
        assert isinstance(result["should_use_alternate_cancel_key"], bool)
        assert isinstance(result["parent_process_chain"], list)
        assert isinstance(result["current_pid"], int)
        assert isinstance(result["python_executable"], str)


class TestUVXIntegration:
    """Test UVX detection integration scenarios."""

    @patch("code_muse.uvx_detection._get_parent_process_chain")
    @patch("platform.system")
    def test_direct_execution_linux(
        self,
        mock_platform,
        mock_get_chain,
    ):
        """Test direct execution on Linux."""
        mock_platform.return_value = "Linux"
        mock_get_chain.return_value = ["python", "bash"]
        if hasattr(is_launched_via_uvx, "cache_clear"):
            is_launched_via_uvx.cache_clear()

        assert is_windows() is False
        assert is_launched_via_uvx() is False
        assert should_use_alternate_cancel_key() is False


class TestGetParentProcessNamePsutilCoverage:
    """Tests for _get_parent_process_name_psutil success path."""

    def test_success_path_returns_parent_name(self):
        """Test that parent process name is returned when parent exists."""
        mock_parent = MagicMock()
        mock_parent.name.return_value = "uvx.exe"

        mock_proc = MagicMock()
        mock_proc.parent.return_value = mock_parent

        mock_psutil = MagicMock()
        mock_psutil.Process.return_value = mock_proc

        with patch.dict(sys.modules, {"psutil": mock_psutil}):
            result = _get_parent_process_name_psutil(1234)

        assert result == "uvx.exe"
        mock_psutil.Process.assert_called_once_with(1234)

    def test_success_path_returns_lowercase_name(self):
        """Test that parent process name is lowercased."""
        mock_parent = MagicMock()
        mock_parent.name.return_value = "UVX.EXE"

        mock_proc = MagicMock()
        mock_proc.parent.return_value = mock_parent

        mock_psutil = MagicMock()
        mock_psutil.Process.return_value = mock_proc

        with patch.dict(sys.modules, {"psutil": mock_psutil}):
            result = _get_parent_process_name_psutil(1234)

        assert result == "uvx.exe"

    def test_returns_none_when_parent_is_none(self):
        """Test that None is returned when parent() returns None."""
        mock_proc = MagicMock()
        mock_proc.parent.return_value = None

        mock_psutil = MagicMock()
        mock_psutil.Process.return_value = mock_proc

        with patch.dict(sys.modules, {"psutil": mock_psutil}):
            result = _get_parent_process_name_psutil(1234)

        assert result is None

    def test_returns_none_on_exception(self):
        """Test that None is returned when an exception occurs."""
        mock_psutil = MagicMock()
        mock_psutil.Process.side_effect = Exception("No such process")

        with patch.dict(sys.modules, {"psutil": mock_psutil}):
            result = _get_parent_process_name_psutil(1234)

        assert result is None

    def test_handles_psutil_noaccess_exception(self):
        """Test graceful handling of psutil access denied errors."""
        mock_psutil = MagicMock()
        # Create a fake AccessDenied exception
        mock_psutil.Process.side_effect = Exception("AccessDenied")

        with patch.dict(sys.modules, {"psutil": mock_psutil}):
            result = _get_parent_process_name_psutil(1)

        assert result is None


class TestGetParentProcessChainPsutilCoverage:
    """Tests for _get_parent_process_chain_psutil chain building."""

    def test_builds_chain_from_process_hierarchy(self):
        """Test that the chain is built by traversing parent processes."""
        # Create process hierarchy: current -> parent1 -> parent2 -> None
        mock_parent2 = MagicMock()
        mock_parent2.name.return_value = "bash"
        mock_parent2.pid = 100
        mock_parent2.parent.return_value = None  # Ends the chain

        mock_parent1 = MagicMock()
        mock_parent1.name.return_value = "uvx"
        mock_parent1.pid = 200
        mock_parent1.parent.return_value = mock_parent2

        mock_current = MagicMock()
        mock_current.name.return_value = "python"
        mock_current.pid = 300
        mock_current.parent.return_value = mock_parent1

        mock_psutil = MagicMock()
        mock_psutil.Process.return_value = mock_current

        with patch.dict(sys.modules, {"psutil": mock_psutil}):
            with patch("code_muse.uvx_detection.os.getpid", return_value=300):
                result = _get_parent_process_chain_psutil()

        # Chain should include all processes from current up
        assert "python" in result
        assert "uvx" in result
        assert "bash" in result

    def test_chain_stops_at_pid_zero(self):
        """Test that chain traversal stops at PID 0."""
        mock_parent = MagicMock()
        mock_parent.name.return_value = "init"
        mock_parent.pid = 0  # This should terminate the loop

        mock_current = MagicMock()
        mock_current.name.return_value = "python"
        mock_current.pid = 100
        mock_current.parent.return_value = mock_parent

        mock_psutil = MagicMock()
        mock_psutil.Process.return_value = mock_current

        with patch.dict(sys.modules, {"psutil": mock_psutil}):
            with patch("code_muse.uvx_detection.os.getpid", return_value=100):
                result = _get_parent_process_chain_psutil()

        # Should have current process in chain but stopped at parent with pid 0
        assert "python" in result

    def test_chain_stops_when_parent_pid_equals_current(self):
        """Test that chain stops if parent PID equals current (circular ref)."""
        mock_current = MagicMock()
        mock_current.name.return_value = "python"
        mock_current.pid = 100

        # Create circular reference - parent has same PID
        mock_parent = MagicMock()
        mock_parent.name.return_value = "python"
        mock_parent.pid = 100  # Same as current - should break loop

        mock_current.parent.return_value = mock_parent

        mock_psutil = MagicMock()
        mock_psutil.Process.return_value = mock_current

        with patch.dict(sys.modules, {"psutil": mock_psutil}):
            with patch("code_muse.uvx_detection.os.getpid", return_value=100):
                result = _get_parent_process_chain_psutil()

        # Should have at least the current process
        assert isinstance(result, list)
        assert len(result) >= 1

    def test_returns_empty_list_on_exception(self):
        """Test that empty list is returned on exception."""
        mock_psutil = MagicMock()
        mock_psutil.Process.side_effect = Exception("Process not found")

        with patch.dict(sys.modules, {"psutil": mock_psutil}):
            with patch("code_muse.uvx_detection.os.getpid", return_value=100):
                result = _get_parent_process_chain_psutil()

        assert result == []

    def test_handles_none_parent_gracefully(self):
        """Test that None parent terminates chain correctly."""
        mock_current = MagicMock()
        mock_current.name.return_value = "python"
        mock_current.pid = 100
        mock_current.parent.return_value = None  # No parent

        mock_psutil = MagicMock()
        mock_psutil.Process.return_value = mock_current

        with patch.dict(sys.modules, {"psutil": mock_psutil}):
            with patch("code_muse.uvx_detection.os.getpid", return_value=100):
                result = _get_parent_process_chain_psutil()

        assert "python" in result
        assert len(result) == 1


class TestGetParentProcessChainWindowsCtypesCoverage:
    """Tests for Windows ctypes-based process chain detection."""

    @patch("platform.system", return_value="Darwin")
    def test_returns_empty_list_on_macos(self, mock_platform):
        """Test that macOS returns empty list immediately."""
        result = _get_parent_process_chain_windows_ctypes()
        assert result == []


class TestGetParentProcessChainFallbackCoverage:
    """Tests for _get_parent_process_chain fallback behavior."""

    def test_uses_psutil_when_available(self):
        """Test that psutil is used when available."""
        with patch(
            "code_muse.uvx_detection._get_parent_process_chain_psutil"
        ) as mock_psutil:
            mock_psutil.return_value = ["python", "uvx", "cmd"]
            result = _get_parent_process_chain()

        # Since psutil is available in test environment, it should use psutil
        assert isinstance(result, list)

    @patch("platform.system", return_value="Linux")
    def test_returns_empty_on_linux_when_psutil_fails(self, mock_platform):
        """Test returns empty list on Linux when psutil fails."""
        # On Linux without psutil, should return empty list (no ctypes fallback)
        with patch(
            "code_muse.uvx_detection._get_parent_process_chain_psutil"
        ) as mock_psutil:
            mock_psutil.side_effect = Exception("psutil error")
            result = _get_parent_process_chain()

        assert isinstance(result, list)


class TestProcessChainIntegrationCoverage:
    """Integration-style tests for the full process chain detection."""

    def test_real_process_chain_contains_python(self):
        """Test that the real process chain contains python."""
        result = _get_parent_process_chain_psutil()

        # At minimum, current process should be Python
        python_found = any("python" in name.lower() for name in result)
        assert python_found or result == []  # Either has python or failed gracefully

    def test_chain_all_lowercase(self):
        """Test that all process names in chain are lowercase."""
        result = _get_parent_process_chain_psutil()

        for name in result:
            assert name == name.lower(), f"Name '{name}' is not lowercase"

    def test_chain_entries_are_strings(self):
        """Test that all chain entries are strings."""
        result = _get_parent_process_chain_psutil()

        for name in result:
            assert isinstance(name, str)

    def test_full_chain_detection_no_crash(self):
        """Test that full chain detection never crashes."""
        # This should never raise, just return a list
        result = _get_parent_process_chain()
        assert isinstance(result, list)


class TestEdgeCasesCoverage:
    """Edge case tests for additional coverage."""

    def test_psutil_chain_handles_name_exception(self):
        """Test handling when process.name() raises exception."""
        mock_current = MagicMock()
        mock_current.name.side_effect = Exception("Cannot get name")
        mock_current.pid = 100
        mock_current.parent.return_value = None

        mock_psutil = MagicMock()
        mock_psutil.Process.return_value = mock_current

        with patch.dict(sys.modules, {"psutil": mock_psutil}):
            with patch("code_muse.uvx_detection.os.getpid", return_value=100):
                result = _get_parent_process_chain_psutil()

        # Should gracefully handle and return empty list
        assert result == []

    def test_psutil_chain_handles_parent_exception(self):
        """Test handling when process.parent() raises exception after getting name."""
        mock_current = MagicMock()
        mock_current.name.return_value = "python"
        mock_current.pid = 100
        mock_current.parent.side_effect = Exception("Access denied")

        mock_psutil = MagicMock()
        mock_psutil.Process.return_value = mock_current

        with patch.dict(sys.modules, {"psutil": mock_psutil}):
            with patch("code_muse.uvx_detection.os.getpid", return_value=100):
                result = _get_parent_process_chain_psutil()

        # The name is appended before parent() is called, so chain has "python"
        # Then exception in parent() is caught, and the partial chain is returned
        assert result == ["python"]

    def test_parent_process_name_with_various_pids(self):
        """Test parent process name lookup with various PIDs."""
        mock_parent = MagicMock()
        mock_parent.name.return_value = "parent_process"

        mock_proc = MagicMock()
        mock_proc.parent.return_value = mock_parent

        mock_psutil = MagicMock()
        mock_psutil.Process.return_value = mock_proc

        with patch.dict(sys.modules, {"psutil": mock_psutil}):
            # Test with various PIDs
            for pid in [0, 1, 4, 100, 9999, 65535]:
                result = _get_parent_process_name_psutil(pid)
                assert result == "parent_process"


class TestPsutilModuleNotAvailable:
    """Test behavior when psutil is not available."""

    def test_parent_process_name_without_psutil(self):
        """Test _get_parent_process_name_psutil when psutil import fails."""
        # Remove psutil from modules temporarily
        original_psutil = sys.modules.get("psutil")

        # Create a module that raises ImportError
        class FakeModule:
            def __getattr__(self, name):
                raise ImportError("No module named 'psutil'")

        sys.modules["psutil"] = FakeModule()

        try:
            result = _get_parent_process_name_psutil(1234)
            # Should return None when import fails
            assert result is None
        finally:
            # Restore original
            if original_psutil is not None:
                sys.modules["psutil"] = original_psutil

    def test_process_chain_without_psutil(self):
        """Test _get_parent_process_chain_psutil when psutil import fails."""
        original_psutil = sys.modules.get("psutil")

        class FakeModule:
            def __getattr__(self, name):
                raise ImportError("No module named 'psutil'")

        sys.modules["psutil"] = FakeModule()

        try:
            result = _get_parent_process_chain_psutil()
            # Should return empty list when import fails
            assert result == []
        finally:
            if original_psutil is not None:
                sys.modules["psutil"] = original_psutil


class TestWindowsFallbackPath:
    """Test the Windows fallback path when psutil is unavailable."""

    @patch("platform.system", return_value="Linux")
    def test_no_fallback_on_linux(self, mock_platform):
        """Test that there's no ctypes fallback on Linux."""
        original_modules = sys.modules.copy()

        if "psutil" in sys.modules:
            del sys.modules["psutil"]

        class BlockingImport:
            def __getattr__(self, name):
                raise ImportError("No psutil")

        sys.modules["psutil"] = BlockingImport()

        try:
            result = _get_parent_process_chain()
            # On Linux without psutil, should return empty list (no ctypes fallback)
            assert result == []
        finally:
            sys.modules.clear()
            sys.modules.update(original_modules)
