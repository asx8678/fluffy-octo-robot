"""Tests for rewind_shortcut.py."""

import time
from pathlib import Path
from unittest.mock import MagicMock, patch

from code_muse.plugins.checkpointing.rewind_shortcut import (
    DoublePressDetector,
    RewindKeyListener,
)


def test_double_press_single_press() -> None:
    d = DoublePressDetector()
    assert d.press() is False


def test_double_press_within_window() -> None:
    d = DoublePressDetector(window_ms=500)
    d.press()
    assert d.press() is True


def test_double_press_outside_window() -> None:
    d = DoublePressDetector(window_ms=1)
    d.press()
    time.sleep(0.01)
    assert d.press() is False


def test_rewind_key_listener_start_stop() -> None:
    callback = MagicMock()
    listener = RewindKeyListener(callback)
    with patch.object(listener._thread, "start") as mock_start:
        listener.start()
        mock_start.assert_called_once()
    listener.stop()
    assert listener._stop.is_set()


def test_rewind_listener_posix_esc(mock_project_root: Path) -> None:
    callback = MagicMock()
    listener = RewindKeyListener(callback)
    with (
        patch("sys.platform", "linux"),
        patch("sys.stdin") as mock_stdin,
        patch("termios.tcgetattr", return_value=[]),
        patch("termios.tcsetattr"),
        patch("tty.setcbreak"),
        patch("select.select") as mock_select,
    ):
        mock_stdin.fileno.return_value = 0
        mock_stdin.read.return_value = "\x1b"
        mock_select.side_effect = [
            ([mock_stdin], [], []),
            ([], [], []),
        ]
        listener._stop.set()
        listener._listen_posix()
        callback.assert_not_called()
